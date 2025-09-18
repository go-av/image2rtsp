// 通用功能模块
const Common = {
    // 显示警告信息
    showAlert: function(type, message) {
        const alertsContainer = document.getElementById('alerts') || document.createElement('div');
        if (!document.getElementById('alerts')) {
            alertsContainer.id = 'alerts';
            document.body.insertBefore(alertsContainer, document.body.firstChild);
        }
        
        const alertDiv = document.createElement('div');
        alertDiv.className = `alert alert-${type}`;
        alertDiv.textContent = message;
        alertsContainer.appendChild(alertDiv);
        
        // 3秒后自动消失
        setTimeout(() => {
            alertDiv.style.opacity = '0';
            alertDiv.style.transition = 'opacity 0.5s ease';
            setTimeout(() => {
                alertsContainer.removeChild(alertDiv);
            }, 500);
        }, 3000);
    },
    
    // 发送API请求
    apiRequest: function(endpoint, method = 'GET', data = null) {
        const options = {
            method: method,
            headers: {}
        };
        
        if (data) {
            options.headers['Content-Type'] = 'application/json';
            options.body = JSON.stringify(data);
        }
        
        return fetch(endpoint, options)
            .then(response => {
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                return response.json();
            })
            .catch(error => {
                console.error('API请求失败:', error);
                Common.showAlert('error', '网络请求失败，请稍后重试');
                throw error;
            });
    },
    
    // 初始化模态框
    initModal: function(modalId, confirmCallback) {
        const modal = document.getElementById(modalId);
        if (!modal) return;
        
        const closeBtn = modal.querySelector('.modal-close');
        const cancelBtn = modal.querySelector('[id^="cancel-"]');
        const confirmBtn = modal.querySelector('[id^="confirm-"]');
        
        const showModal = function() {
            modal.style.display = 'block';
        };
        
        const hideModal = function() {
            modal.style.display = 'none';
        };
        
        if (closeBtn) closeBtn.onclick = hideModal;
        if (cancelBtn) cancelBtn.onclick = hideModal;
        if (confirmBtn && confirmCallback) {
            confirmBtn.onclick = function() {
                confirmCallback();
            };
        }
        
        // 点击模态框外部关闭
        window.addEventListener('click', function(event) {
            if (event.target === modal) {
                hideModal();
            }
        });
        
        return {
            show: showModal,
            hide: hideModal
        };
    },
    
    // 格式化时间
    formatDate: function(date) {
        const d = new Date(date);
        const year = d.getFullYear();
        const month = String(d.getMonth() + 1).padStart(2, '0');
        const day = String(d.getDate()).padStart(2, '0');
        const hours = String(d.getHours()).padStart(2, '0');
        const minutes = String(d.getMinutes()).padStart(2, '0');
        const seconds = String(d.getSeconds()).padStart(2, '0');
        
        return `${year}-${month}-${day} ${hours}:${minutes}:${seconds}`;
    },
    
    // 防抖函数
    debounce: function(func, wait) {
        let timeout;
        return function() {
            const context = this;
            const args = arguments;
            clearTimeout(timeout);
            timeout = setTimeout(() => func.apply(context, args), wait);
        };
    }
};