from flask import Blueprint, render_template, request, send_file, flash, current_app, jsonify
import os
import subprocess
from werkzeug.utils import secure_filename
import uuid
import concurrent.futures
import threading
from functools import partial
import PyPDF2
import pandas as pd
import csv
import io
import logging
import traceback
import datetime

# 配置日志
log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'logs')
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, f'ocr_app_{datetime.datetime.now().strftime("%Y%m%d")}.log')

logging.basicConfig(
    filename=log_file,
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger('ocr_app')

# 添加控制台处理器，同时输出到控制台
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

bp = Blueprint('main', __name__)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'pdf'}

def convert_pdf_to_text(pdf_path):
    """从PDF提取文本内容，支持多语言，并处理竖排文字"""
    text = ""
    logger.info(f"开始从PDF提取文本: {pdf_path}")
    try:
        with open(pdf_path, 'rb') as file:
            reader = PyPDF2.PdfReader(file)
            logger.info(f"PDF页数: {len(reader.pages)}")
            for page_num in range(len(reader.pages)):
                page = reader.pages[page_num]
                page_text = page.extract_text() or ""
                text += page_text + "\n\n"
                logger.debug(f"提取第{page_num+1}页文本，长度: {len(page_text)}")
        
        # 确保文本是UTF-8编码
        if text:
            logger.info(f"成功提取文本，总长度: {len(text)}")
            # 处理竖排文字
            logger.debug("开始处理竖排文字")
            text = process_vertical_text(text)
            logger.debug(f"竖排文字处理完成，处理后文本长度: {len(text)}")
            return text
        logger.warning("未能提取到文本内容")
        return "无法提取文本内容"
    except Exception as e:
        logger.error(f"文本提取错误: {str(e)}")
        logger.error(traceback.format_exc())
        return f"文本提取错误: {str(e)}"

def process_vertical_text(text):
    """处理竖排文字，将其转换为横排格式"""
    import re
    
    # 使用正则表达式查找并替换常见的竖排模式
    # 例如：将"购\n买\n方\n信\n息"替换为"购买方信息"
    common_vertical_patterns = [
        (r'购\s*\n\s*买\s*\n\s*方\s*\n\s*信\s*\n\s*息', '购买方信息'),
        (r'销\s*\n\s*售\s*\n\s*方\s*\n\s*信\s*\n\s*息', '销售方信息'),
        (r'名\s*\n\s*称', '名称'),
        (r'纳\s*\n\s*税\s*\n\s*人\s*\n\s*识\s*\n\s*别\s*\n\s*号', '纳税人识别号'),
        (r'金\s*\n\s*额', '金额'),
        (r'税\s*\n\s*率', '税率'),
        (r'单\s*\n\s*价', '单价'),
        (r'数\s*\n\s*量', '数量'),
        (r'合\s*\n\s*计', '合计'),
        (r'备\s*\n\s*注', '备注'),
        (r'购\s*\n\s*买\s*\n\s*方', '购买方'),
        (r'销\s*\n\s*售\s*\n\s*方', '销售方'),
        (r'信\s*\n\s*息', '信息'),
        (r'开\s*\n\s*票\s*\n\s*日\s*\n\s*期', '开票日期'),
        (r'发\s*\n\s*票\s*\n\s*号\s*\n\s*码', '发票号码'),
        (r'价\s*\n\s*税\s*\n\s*合\s*\n\s*计', '价税合计'),
    ]
    
    # 先尝试替换常见的竖排文字模式
    for pattern, replacement in common_vertical_patterns:
        text = re.sub(pattern, replacement, text)
    
    # 然后尝试识别并合并连续的单字符行
    lines = text.split('\n')
    i = 0
    result_lines = []
    
    while i < len(lines):
        # 如果当前行和后续几行都是单字符，尝试合并它们
        if i + 2 < len(lines) and all(len(lines[i+j].strip()) == 1 for j in range(3)):
            # 收集连续的单字符行
            vertical_chars = []
            j = i
            while j < len(lines) and len(lines[j].strip()) == 1:
                vertical_chars.append(lines[j].strip())
                j += 1
            
            # 合并为横排文字
            result_lines.append(''.join(vertical_chars))
            i = j
        else:
            result_lines.append(lines[i])
            i += 1
    
    return '\n'.join(result_lines)

def convert_pdf_to_csv(pdf_path):
    """从PDF提取文本并转换为CSV格式，修复编码问题"""
    logger.info(f"开始将PDF转换为CSV: {pdf_path}")
    try:
        # 获取文本内容
        logger.debug("调用convert_pdf_to_text获取文本内容")
        text = convert_pdf_to_text(pdf_path)
        
        # 按行分割，保留非空行
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        logger.info(f"提取到{len(lines)}行文本")
        
        # 如果没有内容，返回空列表
        if not lines:
            logger.warning("没有提取到文本内容，返回空列表")
            return []
        
        # 导入正则表达式模块
        import re
        
        # 尝试检测表格结构
        # 1. 检查是否有明显的表格分隔符（如制表符或多个连续空格）
        has_tabs = any('\t' in line for line in lines)
        has_multiple_spaces = any(re.search(r'\s{2,}', line) for line in lines)
        
        logger.debug(f"表格结构检测: 包含制表符={has_tabs}, 包含多个连续空格={has_multiple_spaces}")
        
        # 2. 确定最佳分隔方式
        csv_data = []
        
        if has_tabs:
            # 使用制表符分割
            logger.info("使用制表符分割文本")
            for line in lines:
                fields = line.split('\t')
                csv_data.append(fields)
        elif has_multiple_spaces:
            # 使用多个空格分割
            logger.info("使用多个连续空格分割文本")
            for line in lines:
                fields = re.split(r'\s{2,}', line)
                csv_data.append(fields)
        else:
            # 尝试智能分割
            logger.info("尝试智能分割文本")
            # 检查每行的字符数，如果大部分行的长度相似，可能是固定宽度的文本
            line_lengths = [len(line) for line in lines]
            avg_length = sum(line_lengths) / len(line_lengths)
            similar_lengths = sum(1 for length in line_lengths if abs(length - avg_length) < 10)
            
            logger.debug(f"行长度分析: 平均长度={avg_length:.2f}, 相似长度行数={similar_lengths}/{len(lines)}")
            
            if similar_lengths > len(lines) * 0.7:
                # 可能是固定宽度的文本，尝试按位置分割
                # 简单处理：每行作为一个字段
                logger.info("检测到固定宽度文本，每行作为一个字段")
                for line in lines:
                    csv_data.append([line])
            else:
                # 尝试按逗号分割
                comma_counts = [line.count(',') for line in lines]
                if sum(comma_counts) > len(lines) * 0.5:
                    # 大部分行包含逗号，可能是CSV格式
                    logger.info("检测到逗号分隔符，按逗号分割")
                    for line in lines:
                        fields = line.split(',')
                        csv_data.append(fields)
                else:
                    # 最后尝试按单个空格分割
                    logger.info("使用单个空格分割文本")
                    for line in lines:
                        fields = line.split()
                        if fields:  # 确保非空
                            csv_data.append(fields)
        
        # 确保所有行的字段数一致（填充空字段）
        if csv_data:
            max_fields = max(len(row) for row in csv_data)
            logger.info(f"CSV数据: {len(csv_data)}行, 最大字段数: {max_fields}")
            for i in range(len(csv_data)):
                while len(csv_data[i]) < max_fields:
                    csv_data[i].append("")
        
        return csv_data
    except Exception as e:
        logger.error(f"CSV转换错误: {str(e)}")
        logger.error(traceback.format_exc())
        # 返回原始文本作为单列CSV
        logger.info("尝试返回原始文本作为单列CSV")
        try:
            text = convert_pdf_to_text(pdf_path)
            lines = [line.strip() for line in text.split('\n') if line.strip()]
            logger.info(f"返回{len(lines)}行原始文本")
            return [[line] for line in lines]
        except Exception as ex:
            logger.error(f"返回原始文本也失败: {str(ex)}")
            logger.error(traceback.format_exc())
            return []

def convert_pdf_to_excel(pdf_path):
    """从PDF提取文本并转换为Excel格式"""
    logger.info(f"开始将PDF转换为Excel: {pdf_path}")
    try:
        # 获取CSV数据
        logger.debug("调用convert_pdf_to_csv获取CSV数据")
        csv_data = convert_pdf_to_csv(pdf_path)
        
        # 创建DataFrame
        if csv_data:
            logger.info(f"成功获取CSV数据，行数: {len(csv_data)}")
            # 尝试确定表头
            if len(csv_data) > 1:
                # 假设第一行是表头
                headers = csv_data[0]
                data = csv_data[1:]
                logger.info(f"使用第一行作为表头: {headers}")
                df = pd.DataFrame(data, columns=headers)
            else:
                logger.info("CSV数据只有一行，不使用表头")
                df = pd.DataFrame(csv_data)
            
            logger.info(f"创建DataFrame成功，大小: {df.shape}")
            return df
        
        logger.warning("没有CSV数据，返回空DataFrame")
        return pd.DataFrame()  # 返回空DataFrame
    except Exception as e:
        logger.error(f"Excel转换错误: {str(e)}")
        logger.error(traceback.format_exc())
        return pd.DataFrame()  # 出错时返回空DataFrame

def process_pdf(file_info, upload_folder, output_format='pdf'):
    input_path, output_path = file_info
    try:
        # 添加详细日志
        logger.info(f"开始处理文件: {input_path}")
        logger.info(f"输出路径: {output_path}")
        logger.info(f"输出格式: {output_format}")
        
        # 检查输入文件
        if not os.path.exists(input_path):
            logger.error(f"输入文件不存在: {input_path}")
            raise Exception(f"输入文件不存在: {input_path}")
        
        logger.info(f"文件大小: {os.path.getsize(input_path)} 字节")
            
        # 添加verbose参数获取更多信息
        ocr_command = [
            'ocrmypdf',
            '--force-ocr',          # 强制对所有页面进行OCR处理
            '--optimize', '1',       # 优化PDF大小
            '--deskew',             # 自动纠偏
            '--clean',              # 清理图像
            '--language', 'chi_sim+chi_tra+eng',  # 简体中文+繁体中文+英文
            '--verbose',            # 详细输出
            '--output-type', 'pdf', # 指定输出类型
            '--jobs', '1',          # 单线程处理
            input_path,
            output_path
        ]
        
        logger.info(f"执行OCR命令: {' '.join(ocr_command)}")
        
        result = subprocess.run(ocr_command, capture_output=True, text=True)
        
        # 记录命令输出
        logger.info("OCR命令输出:")
        logger.info(result.stdout)
        
        if result.returncode != 0:
            logger.error("OCR处理失败，错误输出:")
            logger.error(result.stderr)
            raise Exception(f"OCR处理失败: {result.stderr}")
            
        if not os.path.exists(output_path):
            logger.error("输出文件未生成")
            raise Exception("输出文件未生成")
            
        logger.info(f"OCR处理成功: {output_path}")
        logger.info(f"处理后文件大小: {os.path.getsize(output_path)} 字节")
        
        # 根据输出格式转换文件
        if output_format != 'pdf':
            converted_path = output_path.replace('.pdf', f'.{output_format}')
            logger.info(f"开始转换为{output_format}格式: {converted_path}")
            
            if output_format == 'txt':
                # 转换为TXT
                logger.info("开始提取文本内容")
                text_content = convert_pdf_to_text(output_path)
                logger.info(f"提取的文本长度: {len(text_content)}")
                
                try:
                    with open(converted_path, 'w', encoding='utf-8') as f:
                        f.write(text_content)
                    logger.info(f"文本内容已写入文件: {converted_path}")
                except Exception as e:
                    logger.error(f"写入文本文件失败: {str(e)}")
                    logger.error(traceback.format_exc())
                    raise
                
                # 删除原PDF文件
                os.remove(output_path)
                logger.info(f"已删除原PDF文件: {output_path}")
                return converted_path
                
            elif output_format == 'csv':
                # 转换为CSV，使用pandas处理编码问题
                logger.info("开始转换为CSV格式")
                csv_data = convert_pdf_to_csv(output_path)
                logger.info(f"CSV数据行数: {len(csv_data)}")
                
                # 创建DataFrame
                if csv_data:
                    if len(csv_data) > 1:
                        # 假设第一行是表头
                        headers = csv_data[0]
                        data = csv_data[1:]
                        logger.info(f"使用第一行作为表头: {headers}")
                        df = pd.DataFrame(data, columns=headers)
                    else:
                        logger.info("CSV数据只有一行，不使用表头")
                        df = pd.DataFrame(csv_data)
                    
                    try:
                        # 使用pandas的to_csv方法，添加UTF-8-BOM标记
                        df.to_csv(converted_path, index=False, encoding='utf-8-sig')
                        logger.info(f"CSV数据已写入文件: {converted_path}")
                    except Exception as e:
                        logger.error(f"写入CSV文件失败: {str(e)}")
                        logger.error(traceback.format_exc())
                        raise
                else:
                    logger.warning("没有提取到CSV数据，创建空文件")
                    # 如果没有数据，创建空文件
                    with open(converted_path, 'w', encoding='utf-8-sig') as f:
                        f.write('')
                
                # 删除原PDF文件
                os.remove(output_path)
                logger.info(f"已删除原PDF文件: {output_path}")
                return converted_path
                
            elif output_format == 'xlsx':
                try:
                    # 转换为XLSX
                    logger.info("开始转换为Excel格式")
                    df = convert_pdf_to_excel(output_path)
                    
                    # 确保DataFrame不为空
                    if df.empty:
                        logger.warning("提取的DataFrame为空，创建包含提示信息的DataFrame")
                        # 如果DataFrame为空，创建一个包含提示信息的DataFrame
                        df = pd.DataFrame([["无法从PDF中提取表格数据"]])
                    else:
                        logger.info(f"提取的DataFrame大小: {df.shape}")
                    
                    try:
                        # 使用openpyxl引擎保存为xlsx格式
                        df.to_excel(converted_path, index=False, engine='openpyxl')
                        logger.info(f"Excel数据已写入文件: {converted_path}")
                    except Exception as e:
                        logger.error(f"写入Excel文件失败: {str(e)}")
                        logger.error(traceback.format_exc())
                        raise
                    
                    # 删除原PDF文件
                    os.remove(output_path)
                    logger.info(f"已删除原PDF文件: {output_path}")
                    return converted_path
                except Exception as e:
                    logger.error(f"Excel转换错误: {str(e)}")
                    logger.error(traceback.format_exc())
                    # 如果Excel转换失败，尝试创建一个简单的Excel文件
                    simple_df = pd.DataFrame([["PDF转换为Excel失败", str(e)]])
                    
                    try:
                        simple_df.to_excel(converted_path, index=False, engine='openpyxl')
                        logger.info(f"错误信息已写入Excel文件: {converted_path}")
                    except Exception as ex:
                        logger.error(f"写入错误信息到Excel文件失败: {str(ex)}")
                        logger.error(traceback.format_exc())
                        raise
                    
                    # 删除原PDF文件
                    os.remove(output_path)
                    logger.info(f"已删除原PDF文件: {output_path}")
                    return converted_path
        
        logger.info(f"返回处理后的文件: {output_path}")
        return output_path
    except Exception as e:
        logger.error(f"处理PDF文件失败: {str(e)}")
        logger.error(traceback.format_exc())
        if os.path.exists(output_path):
            os.remove(output_path)
            logger.info(f"已删除输出文件: {output_path}")
        raise e
    finally:
        if os.path.exists(input_path):
            os.remove(input_path)
            logger.info(f"已删除输入文件: {input_path}")

@bp.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        logger.info("收到POST请求")
        
        # 检查是否有文件上传
        if 'files[]' not in request.files:
            logger.warning("没有选择文件")
            return jsonify({'error': '没有选择文件'}), 400
        
        files = request.files.getlist('files[]')
        logger.info(f"上传的文件数量: {len(files)}")
        
        if not files or files[0].filename == '':
            logger.warning("没有选择文件或文件名为空")
            return jsonify({'error': '没有选择文件'}), 400
            
        if len(files) > current_app.config['MAX_FILES']:
            logger.warning(f"文件数量超过限制: {len(files)} > {current_app.config['MAX_FILES']}")
            return jsonify({'error': f'最多只能同时处理 {current_app.config["MAX_FILES"]} 个文件'}), 400

        # 准备处理任务
        tasks = []
        for i, file in enumerate(files):
            logger.info(f"处理第{i+1}个文件: {file.filename}")
            if file and allowed_file(file.filename):
                filename = str(uuid.uuid4()) + '.pdf'
                input_path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'input_' + filename)
                output_path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'output_' + filename)
                
                logger.debug(f"保存上传文件到: {input_path}")
                file.save(input_path)
                tasks.append((input_path, output_path))
            else:
                logger.warning(f"文件类型不允许: {file.filename}")

        # 获取输出格式
        output_format = request.form.get('output_format', 'pdf')
        if output_format not in ['pdf', 'txt', 'csv', 'xlsx']:
            logger.warning(f"不支持的输出格式: {output_format}，使用默认格式pdf")
            output_format = 'pdf'  # 默认为PDF
            
        logger.info(f"选择的输出格式: {output_format}")
            
        # 并发处理文件
        results = []
        logger.info(f"开始并发处理文件，并发数: {current_app.config['CONCURRENT_PROCESSES']}")
        with concurrent.futures.ThreadPoolExecutor(max_workers=current_app.config['CONCURRENT_PROCESSES']) as executor:
            process_func = partial(process_pdf, upload_folder=current_app.config['UPLOAD_FOLDER'], output_format=output_format)
            futures = [executor.submit(process_func, task) for task in tasks]
            
            for future in concurrent.futures.as_completed(futures):
                try:
                    output_path = future.result()
                    logger.info(f"文件处理成功: {output_path}")
                    results.append(output_path)
                except Exception as e:
                    logger.error(f"文件处理失败: {str(e)}")
                    logger.error(traceback.format_exc())
                    return jsonify({'error': f'OCR处理失败: {str(e)}'}), 500

        logger.info(f"所有文件处理完成，成功数量: {len(results)}")
        
        # 如果只有一个文件，直接返回
        if len(results) == 1:
            # 根据输出格式修改文件扩展名
            original_filename = secure_filename(files[0].filename)
            base_filename = os.path.splitext(original_filename)[0]
            download_name = f'ocr_{base_filename}.{output_format}'
            
            logger.info(f"返回单个处理后的文件: {download_name}")
            return send_file(results[0], as_attachment=True,
                           download_name=download_name)
                           
        # TODO: 如果是多个文件，可以考虑打包成zip返回
        # 当前临时处理：返回第一个成功的文件
        original_filename = secure_filename(files[0].filename)
        base_filename = os.path.splitext(original_filename)[0]
        download_name = f'ocr_{base_filename}.{output_format}'
        
        logger.info(f"返回多个文件中的第一个: {download_name}")
        return send_file(results[0], as_attachment=True,
                        download_name=download_name)
    
    # GET请求，返回首页
    logger.info("收到GET请求，返回首页")
    return render_template('index.html')
