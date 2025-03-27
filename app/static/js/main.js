document.addEventListener('DOMContentLoaded', function() {
    const fileInput = document.getElementById('files');
    const submitButton = document.querySelector('button[type="submit"]');
    const form = document.querySelector('form');
    const progressContainer = document.getElementById('progress-container');
    const progressBar = progressContainer.querySelector('.progress-bar');
    const fileList = document.getElementById('file-list');

    fileInput.addEventListener('change', function() {
        fileList.innerHTML = '';
        let validFiles = true;
        
        Array.from(this.files).forEach(file => {
            const fileName = file.name;
            if (!fileName.toLowerCase().endsWith('.pdf')) {
                validFiles = false;
                alert('请只选择PDF文件！');
                this.value = '';
                return;
            }
            
            // 显示文件列表
            const fileItem = document.createElement('div');
            fileItem.className = 'alert alert-info';
            fileItem.innerHTML = `
                <div class="d-flex justify-content-between align-items-center">
                    <span>${fileName}</span>
                    <span class="badge bg-secondary">等待处理</span>
                </div>
            `;
            fileList.appendChild(fileItem);
        });

        if (validFiles && this.files.length > 0) {
            submitButton.disabled = false;
            submitButton.innerHTML = '开始OCR处理';
        }
    });

    form.addEventListener('submit', async function(e) {
        e.preventDefault();
        submitButton.disabled = true;
        submitButton.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> 处理中...';
        
        const files = Array.from(fileInput.files);
        let processed = 0;
        
        progressContainer.classList.remove('d-none');
        progressBar.style.width = '0%';
        progressBar.textContent = `0/${files.length}`;

        for (let i = 0; i < files.length; i++) {
            const file = files[i];
            const formData = new FormData();
            formData.append('files[]', file);
            
            // 添加输出格式
            const outputFormat = document.getElementById('output_format').value;
            formData.append('output_format', outputFormat);
            
            const fileItem = fileList.children[i];
            const statusBadge = fileItem.querySelector('.badge');
            statusBadge.className = 'badge bg-warning';
            statusBadge.textContent = '处理中...';

            try {
                const response = await fetch('/', {
                    method: 'POST',
                    body: formData
                });

                if (!response.ok) {
                    const data = await response.json();
                    throw new Error(data.error || '处理失败');
                }

                const blob = await response.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                
                // 根据选择的输出格式修改文件扩展名
                const outputFormat = document.getElementById('output_format').value;
                const fileName = file.name;
                const baseName = fileName.substring(0, fileName.lastIndexOf('.')) || fileName;
                
                // 设置正确的文件扩展名和MIME类型
                let mimeType = 'application/pdf';
                if (outputFormat === 'txt') {
                    mimeType = 'text/plain';
                } else if (outputFormat === 'csv') {
                    mimeType = 'text/csv';
                } else if (outputFormat === 'xlsx') {
                    mimeType = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';
                }
                
                // 设置下载文件名
                a.download = `ocr_${baseName}.${outputFormat}`;
                
                document.body.appendChild(a);
                a.click();
                window.URL.revokeObjectURL(url);
                document.body.removeChild(a);

                statusBadge.className = 'badge bg-success';
                statusBadge.textContent = '完成';
            } catch (error) {
                console.error('Error:', error);
                statusBadge.className = 'badge bg-danger';
                statusBadge.textContent = '失败';
            }

            processed++;
            progressBar.style.width = `${(processed / files.length) * 100}%`;
            progressBar.textContent = `${processed}/${files.length}`;
        }

        submitButton.disabled = false;
        submitButton.innerHTML = '开始OCR处理';
    });
});
