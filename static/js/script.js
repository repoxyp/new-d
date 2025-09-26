class VideoDownloader {
    constructor() {
        this.currentDownloadId = null;
        this.currentVideoInfo = null;
        this.initializeEventListeners();
        this.loadDownloadHistory();
    }

    initializeEventListeners() {
        // URL input validation
        document.getElementById('urlInput').addEventListener('input', (e) => {
            this.validateUrl(e.target.value);
        });

        // Fetch video info
        document.getElementById('fetchInfoBtn').addEventListener('click', () => {
            this.fetchVideoInfo();
        });

        // Batch download toggle
        document.getElementById('toggleBatchBtn').addEventListener('click', () => {
            this.toggleBatchInputs();
        });

        // Batch download
        document.getElementById('batchDownloadBtn').addEventListener('click', () => {
            this.startBatchDownload();
        });

        // Download button
        document.getElementById('downloadBtn').addEventListener('click', () => {
            this.startDownload();
        });
    }

    validateUrl(url) {
        const btn = document.getElementById('fetchInfoBtn');
        const errorDiv = document.getElementById('urlError');
        
        if (url.length < 10) {
            btn.disabled = true;
            errorDiv.style.display = 'none';
            return;
        }

        try {
            new URL(url);
            btn.disabled = false;
            errorDiv.style.display = 'none';
        } catch (_) {
            btn.disabled = true;
            errorDiv.textContent = '❌ Please enter a valid URL';
            errorDiv.style.display = 'block';
        }
    }

    async fetchVideoInfo() {
        const url = document.getElementById('urlInput').value.trim();
        const loadingDiv = document.getElementById('formatLoading');
        const formatSection = document.getElementById('formatSection');
        
        if (!url) return;

        try {
            loadingDiv.style.display = 'block';
            formatSection.style.display = 'none';

            const response = await fetch('/get_info', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ url: url })
            });

            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.error || 'Failed to fetch video info');
            }

            this.currentVideoInfo = data;
            this.displayVideoInfo(data);
            this.displayFormats(data.formats);
            
        } catch (error) {
            this.showError('urlError', error.message);
        } finally {
            loadingDiv.style.display = 'none';
        }
    }

    displayVideoInfo(info) {
        const videoInfoDiv = document.getElementById('videoInfo');
        const thumbnail = document.getElementById('videoThumbnail');
        const title = document.getElementById('videoTitle');
        const duration = document.getElementById('videoDuration');

        thumbnail.src = info.thumbnail;
        title.textContent = info.title;
        
        // Duration format
        const mins = Math.floor(info.duration / 60);
        const secs = info.duration % 60;
        duration.textContent = `Duration: ${mins}:${secs.toString().padStart(2, '0')}`;
        
        videoInfoDiv.style.display = 'flex';
    }

    displayFormats(formats) {
        const formatGrid = document.getElementById('formatGrid');
        const formatSection = document.getElementById('formatSection');
        
        formatGrid.innerHTML = '';
        
        formats.forEach(format => {
            const formatItem = document.createElement('div');
            formatItem.className = 'format-item';
            formatItem.innerHTML = `
                <div class="format-name">${format.name}</div>
                <small>${format.type.toUpperCase()} • ${format.ext}</small>
            `;
            
            formatItem.addEventListener('click', () => {
                // Remove previous selection
                document.querySelectorAll('.format-item').forEach(item => {
                    item.classList.remove('selected');
                });
                
                // Add selection to current item
                formatItem.classList.add('selected');
                
                // Store selected format
                this.selectedFormat = format;
                
                // Show download button
                document.getElementById('progressSection').style.display = 'block';
                document.getElementById('downloadBtn').style.display = 'block';
            });
            
            formatGrid.appendChild(formatItem);
        });
        
        formatSection.style.display = 'block';
    }

    async startDownload() {
        if (!this.selectedFormat || !this.currentVideoInfo) {
            this.showError('urlError', 'Please select a format first');
            return;
        }

        const downloadBtn = document.getElementById('downloadBtn');
        downloadBtn.disabled = true;
        downloadBtn.innerHTML = '⏳ Starting Download...';

        try {
            const response = await fetch('/start_download', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    url: document.getElementById('urlInput').value.trim(),
                    format_id: this.selectedFormat.format_id,
                    title: this.currentVideoInfo.title
                })
            });

            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.error || 'Download failed');
            }

            this.currentDownloadId = data.download_id;
            this.monitorDownloadProgress();

        } catch (error) {
            this.showError('urlError', error.message);
            downloadBtn.disabled = false;
            downloadBtn.innerHTML = '⬇️ Download Now';
        }
    }

    async monitorDownloadProgress() {
        if (!this.currentDownloadId) return;

        const progressFill = document.getElementById('progressFill');
        const progressText = document.getElementById('progressText');
        const downloadSpeed = document.getElementById('downloadSpeed');
        const fileSize = document.getElementById('fileSize');
        const downloadBtn = document.getElementById('downloadBtn');

        const checkProgress = async () => {
            try {
                const response = await fetch(`/download_status/${this.currentDownloadId}`);
                const status = await response.json();

                if (status.status === 'downloading') {
                    // Update progress bar
                    const percent = parseFloat(status.percent) || 0;
                    progressFill.style.width = `${percent}%`;
                    progressText.textContent = status.percent;
                    downloadSpeed.textContent = status.speed;
                    fileSize.textContent = `${status.downloaded} / ${status.total_size}`;

                    // Continue checking
                    setTimeout(checkProgress, 1000);
                } else if (status.status === 'finished') {
                    // Download completed
                    progressFill.style.width = '100%';
                    progressText.textContent = '100%';
                    downloadSpeed.textContent = 'Completed';
                    
                    // Enable download button for file
                    downloadBtn.disabled = false;
                    downloadBtn.innerHTML = '💾 Save File';
                    downloadBtn.onclick = () => this.downloadFile();

                    this.addToDownloadHistory(this.currentVideoInfo.title, this.selectedFormat.name);
                    
                } else if (status.status === 'error') {
                    this.showError('urlError', status.error);
                    downloadBtn.disabled = false;
                    downloadBtn.innerHTML = '⬇️ Download Now';
                }
            } catch (error) {
                console.error('Error checking progress:', error);
                setTimeout(checkProgress, 2000);
            }
        };

        checkProgress();
    }

    async downloadFile() {
        if (!this.currentDownloadId) return;

        try {
            const response = await fetch(`/download_file/${this.currentDownloadId}`);
            
            if (!response.ok) {
                throw new Error('Failed to download file');
            }

            // Create blob and download
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = this.currentVideoInfo.title + '.' + this.selectedFormat.ext;
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);

            // Reset UI
            this.resetDownloadUI();

        } catch (error) {
            this.showError('urlError', error.message);
        }
    }

    resetDownloadUI() {
        document.getElementById('progressSection').style.display = 'none';
        document.getElementById('downloadBtn').style.display = 'none';
        document.getElementById('progressFill').style.width = '0%';
        this.currentDownloadId = null;
    }

    toggleBatchInputs() {
        const batchInputs = document.getElementById('batchInputs');
        const isVisible = batchInputs.style.display !== 'none';
        batchInputs.style.display = isVisible ? 'none' : 'block';
    }

    async startBatchDownload() {
        const urlsText = document.getElementById('batchUrls').value.trim();
        if (!urlsText) return;

        const urls = urlsText.split('\n').filter(url => url.trim()).map(url => url.trim());
        const batchProgress = document.getElementById('batchProgress');
        
        batchProgress.style.display = 'block';
        batchProgress.innerHTML = '<div class="loading">🚀 Starting batch download...</div>';

        try {
            const response = await fetch('/batch_download', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    urls: urls,
                    format_id: this.selectedFormat?.format_id || 'best'
                })
            });

            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.error || 'Batch download failed');
            }

            this.monitorBatchProgress(data.batch_id, urls.length);

        } catch (error) {
            batchProgress.innerHTML = `<div class="error-message">❌ ${error.message}</div>`;
        }
    }

    async monitorBatchProgress(batchId, total) {
        const batchProgress = document.getElementById('batchProgress');
        
        const checkProgress = async () => {
            try {
                const response = await fetch(`/download_status/${batchId}`);
                const status = await response.json();

                if (status.status === 'processing') {
                    const completed = status.completed || 0;
                    const progress = Math.round((completed / total) * 100);
                    
                    batchProgress.innerHTML = `
                        <div class="progress-bar">
                            <div class="progress-fill" style="width: ${progress}%"></div>
                        </div>
                        <div class="progress-info">
                            <span>${completed}/${total} completed (${progress}%)</span>
                        </div>
                    `;

                    setTimeout(checkProgress, 2000);
                } else if (status.status === 'finished') {
                    batchProgress.innerHTML = `
                        <div class="success-message">
                            ✅ Batch download completed! ${total} files downloaded.
                        </div>
                    `;
                }
            } catch (error) {
                console.error('Error checking batch progress:', error);
                setTimeout(checkProgress, 2000);
            }
        };

        checkProgress();
    }

    addToDownloadHistory(title, format) {
        const historyList = document.getElementById('historyList');
        const historyItem = document.createElement('div');
        historyItem.className = 'history-item';
        
        const now = new Date();
        const timeString = now.toLocaleTimeString();
        
        historyItem.innerHTML = `
            <span><strong>${title}</strong></span>
            <span>${format} • ${timeString}</span>
        `;
        
        historyList.insertBefore(historyItem, historyList.firstChild);
        
        // Limit history to 10 items
        if (historyList.children.length > 10) {
            historyList.removeChild(historyList.lastChild);
        }
        
        this.saveDownloadHistory();
    }

    loadDownloadHistory() {
        const history = JSON.parse(localStorage.getItem('downloadHistory') || '[]');
        const historyList = document.getElementById('historyList');
        
        history.forEach(item => {
            const historyItem = document.createElement('div');
            historyItem.className = 'history-item';
            historyItem.innerHTML = `
                <span><strong>${item.title}</strong></span>
                <span>${item.format} • ${item.time}</span>
            `;
            historyList.appendChild(historyItem);
        });
    }

    saveDownloadHistory() {
        const historyItems = document.querySelectorAll('.history-item');
        const history = Array.from(historyItems).map(item => {
            const spans = item.querySelectorAll('span');
            return {
                title: spans[0].textContent.replace('<strong>', '').replace('</strong>', ''),
                format: spans[1].textContent.split('•')[0].trim(),
                time: spans[1].textContent.split('•')[1].trim()
            };
        });
        
        localStorage.setItem('downloadHistory', JSON.stringify(history));
    }

    showError(elementId, message) {
        const errorDiv = document.getElementById(elementId);
        errorDiv.textContent = `❌ ${message}`;
        errorDiv.style.display = 'block';
        
        // Auto-hide error after 5 seconds
        setTimeout(() => {
            errorDiv.style.display = 'none';
        }, 5000);
    }
}

// Initialize the downloader when page loads
document.addEventListener('DOMContentLoaded', () => {
    new VideoDownloader();
});