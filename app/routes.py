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

bp = Blueprint('main', __name__)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'pdf'}

def convert_pdf_to_text(pdf_path):
    """从PDF提取文本内容，支持多语言"""
    text = ""
    try:
        with open(pdf_path, 'rb') as file:
            reader = PyPDF2.PdfReader(file)
            for page_num in range(len(reader.pages)):
                page = reader.pages[page_num]
                page_text = page.extract_text() or ""
                text += page_text + "\n\n"
        
        # 确保文本是UTF-8编码
        if text:
            # 尝试检测编码并转换为UTF-8
            return text
        return "无法提取文本内容"
    except Exception as e:
        print(f"文本提取错误: {str(e)}")
        return f"文本提取错误: {str(e)}"

def convert_pdf_to_csv(pdf_path):
    """从PDF提取文本并转换为CSV格式，修复编码问题"""
    try:
        # 获取文本内容
        text = convert_pdf_to_text(pdf_path)
        
        # 按行分割，保留非空行
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        
        # 如果没有内容，返回空列表
        if not lines:
            return []
        
        # 导入正则表达式模块
        import re
        
        # 尝试检测表格结构
        # 1. 检查是否有明显的表格分隔符（如制表符或多个连续空格）
        has_tabs = any('\t' in line for line in lines)
        has_multiple_spaces = any(re.search(r'\s{2,}', line) for line in lines)
        
        # 2. 确定最佳分隔方式
        csv_data = []
        
        if has_tabs:
            # 使用制表符分割
            for line in lines:
                fields = line.split('\t')
                csv_data.append(fields)
        elif has_multiple_spaces:
            # 使用多个空格分割
            for line in lines:
                fields = re.split(r'\s{2,}', line)
                csv_data.append(fields)
        else:
            # 尝试智能分割
            # 检查每行的字符数，如果大部分行的长度相似，可能是固定宽度的文本
            line_lengths = [len(line) for line in lines]
            avg_length = sum(line_lengths) / len(line_lengths)
            similar_lengths = sum(1 for length in line_lengths if abs(length - avg_length) < 10)
            
            if similar_lengths > len(lines) * 0.7:
                # 可能是固定宽度的文本，尝试按位置分割
                # 简单处理：每行作为一个字段
                for line in lines:
                    csv_data.append([line])
            else:
                # 尝试按逗号分割
                comma_counts = [line.count(',') for line in lines]
                if sum(comma_counts) > len(lines) * 0.5:
                    # 大部分行包含逗号，可能是CSV格式
                    for line in lines:
                        fields = line.split(',')
                        csv_data.append(fields)
                else:
                    # 最后尝试按单个空格分割
                    for line in lines:
                        fields = line.split()
                        if fields:  # 确保非空
                            csv_data.append(fields)
        
        # 确保所有行的字段数一致（填充空字段）
        if csv_data:
            max_fields = max(len(row) for row in csv_data)
            for i in range(len(csv_data)):
                while len(csv_data[i]) < max_fields:
                    csv_data[i].append("")
        
        return csv_data
    except Exception as e:
        print(f"CSV转换错误: {str(e)}")
        # 返回原始文本作为单列CSV
        text = convert_pdf_to_text(pdf_path)
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        return [[line] for line in lines]

def convert_pdf_to_excel(pdf_path):
    """从PDF提取文本并转换为Excel格式"""
    csv_data = convert_pdf_to_csv(pdf_path)
    
    # 创建DataFrame
    if csv_data:
        # 尝试确定表头
        if len(csv_data) > 1:
            # 假设第一行是表头
            headers = csv_data[0]
            data = csv_data[1:]
            df = pd.DataFrame(data, columns=headers)
        else:
            df = pd.DataFrame(csv_data)
        return df
    return pd.DataFrame()  # 返回空DataFrame

def process_pdf(file_info, upload_folder, output_format='pdf'):
    input_path, output_path = file_info
    try:
        # 添加详细日志
        print(f"开始处理文件: {input_path}")
        print(f"输出路径: {output_path}")
        print(f"输出格式: {output_format}")
        
        # 检查输入文件
        if not os.path.exists(input_path):
            raise Exception(f"输入文件不存在: {input_path}")
            
        # 添加verbose参数获取更多信息
        result = subprocess.run([
            'ocrmypdf',
            '--skip-text',          # 保留原有文本
            '--optimize', '1',       # 优化PDF大小
            '--deskew',             # 自动纠偏
            '--clean',              # 清理图像
            '--language', 'chi_sim+chi_tra+eng',  # 简体中文+繁体中文+英文
            '--verbose',            # 详细输出
            '--output-type', 'pdf', # 指定输出类型
            '--jobs', '1',          # 单线程处理
            input_path,
            output_path
        ], capture_output=True, text=True)
        
        # 打印命令输出
        print("命令输出:")
        print(result.stdout)
        
        if result.returncode != 0:
            print("错误输出:")
            print(result.stderr)
            raise Exception(f"OCR处理失败: {result.stderr}")
            
        if not os.path.exists(output_path):
            raise Exception("输出文件未生成")
            
        print(f"文件处理成功: {output_path}")
        
        # 根据输出格式转换文件
        if output_format != 'pdf':
            converted_path = output_path.replace('.pdf', f'.{output_format}')
            
            if output_format == 'txt':
                # 转换为TXT
                text_content = convert_pdf_to_text(output_path)
                with open(converted_path, 'w', encoding='utf-8') as f:
                    f.write(text_content)
                
                # 删除原PDF文件
                os.remove(output_path)
                return converted_path
                
            elif output_format == 'csv':
                # 转换为CSV，使用pandas处理编码问题
                csv_data = convert_pdf_to_csv(output_path)
                
                # 创建DataFrame
                if csv_data:
                    if len(csv_data) > 1:
                        # 假设第一行是表头
                        headers = csv_data[0]
                        data = csv_data[1:]
                        df = pd.DataFrame(data, columns=headers)
                    else:
                        df = pd.DataFrame(csv_data)
                    
                    # 使用pandas的to_csv方法，添加UTF-8-BOM标记
                    df.to_csv(converted_path, index=False, encoding='utf-8-sig')
                else:
                    # 如果没有数据，创建空文件
                    with open(converted_path, 'w', encoding='utf-8-sig') as f:
                        f.write('')
                
                # 删除原PDF文件
                os.remove(output_path)
                return converted_path
                
            elif output_format == 'xlsx':
                try:
                    # 转换为XLSX
                    df = convert_pdf_to_excel(output_path)
                    
                    # 确保DataFrame不为空
                    if df.empty:
                        # 如果DataFrame为空，创建一个包含提示信息的DataFrame
                        df = pd.DataFrame([["无法从PDF中提取表格数据"]])
                    
                    # 使用openpyxl引擎保存为xlsx格式
                    df.to_excel(converted_path, index=False, engine='openpyxl')
                    
                    # 删除原PDF文件
                    os.remove(output_path)
                    return converted_path
                except Exception as e:
                    print(f"Excel转换错误: {str(e)}")
                    # 如果Excel转换失败，尝试创建一个简单的Excel文件
                    simple_df = pd.DataFrame([["PDF转换为Excel失败", str(e)]])
                    simple_df.to_excel(converted_path, index=False, engine='openpyxl')
                    
                    # 删除原PDF文件
                    os.remove(output_path)
                    return converted_path
        
        return output_path
    except Exception as e:
        if os.path.exists(output_path):
            os.remove(output_path)
        raise e
    finally:
        if os.path.exists(input_path):
            os.remove(input_path)

@bp.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        if 'files[]' not in request.files:
            return jsonify({'error': '没有选择文件'}), 400
        
        files = request.files.getlist('files[]')
        
        if not files or files[0].filename == '':
            return jsonify({'error': '没有选择文件'}), 400
            
        if len(files) > current_app.config['MAX_FILES']:
            return jsonify({'error': f'最多只能同时处理 {current_app.config["MAX_FILES"]} 个文件'}), 400

        # 准备处理任务
        tasks = []
        for file in files:
            if file and allowed_file(file.filename):
                filename = str(uuid.uuid4()) + '.pdf'
                input_path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'input_' + filename)
                output_path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'output_' + filename)
                
                file.save(input_path)
                tasks.append((input_path, output_path))

        # 获取输出格式
        output_format = request.form.get('output_format', 'pdf')
        if output_format not in ['pdf', 'txt', 'csv', 'xlsx']:
            output_format = 'pdf'  # 默认为PDF
            
        print(f"选择的输出格式: {output_format}")
            
        # 并发处理文件
        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=current_app.config['CONCURRENT_PROCESSES']) as executor:
            process_func = partial(process_pdf, upload_folder=current_app.config['UPLOAD_FOLDER'], output_format=output_format)
            futures = [executor.submit(process_func, task) for task in tasks]
            
            for future in concurrent.futures.as_completed(futures):
                try:
                    output_path = future.result()
                    results.append(output_path)
                except Exception as e:
                    return jsonify({'error': f'OCR处理失败: {str(e)}'}), 500

        # 如果只有一个文件，直接返回
        if len(results) == 1:
            # 根据输出格式修改文件扩展名
            original_filename = secure_filename(files[0].filename)
            base_filename = os.path.splitext(original_filename)[0]
            download_name = f'ocr_{base_filename}.{output_format}'
            
            return send_file(results[0], as_attachment=True,
                           download_name=download_name)
                           
        # TODO: 如果是多个文件，可以考虑打包成zip返回
        # 当前临时处理：返回第一个成功的文件
        original_filename = secure_filename(files[0].filename)
        base_filename = os.path.splitext(original_filename)[0]
        download_name = f'ocr_{base_filename}.{output_format}'
        
        return send_file(results[0], as_attachment=True,
                        download_name=download_name)
                    
    return render_template('index.html')
