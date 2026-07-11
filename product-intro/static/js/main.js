document.addEventListener('DOMContentLoaded', () => {
    // ==========================================================================
    // 1. 全域 UI 互動: Flash 訊息自動淡出
    // ==========================================================================
    const flashMessages = document.querySelectorAll('.flash-message');
    flashMessages.forEach(msg => {
        setTimeout(() => {
            msg.style.opacity = '0';
            msg.style.transform = 'translateY(-10px)';
            msg.style.transition = 'all 0.5s ease';
            setTimeout(() => msg.remove(), 500);
        }, 3000);
    });

    // ==========================================================================
    // 2. 產品詳細頁: 在線 PDF 檢視器（僅預覽，無下載）
    // ==========================================================================
    const viewButtons = document.querySelectorAll('.btn-icon.view');
    const viewerWrapper = document.getElementById('pdf-viewer-wrapper');
    const pdfIframe = document.getElementById('pdf-iframe');
    const viewerTitle = document.getElementById('viewer-title');
    const closeViewerBtn = document.getElementById('close-viewer-btn');

    if (viewButtons && viewerWrapper && pdfIframe) {
        viewButtons.forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.preventDefault();
                const viewUrl = btn.getAttribute('data-url');
                const displayName = btn.getAttribute('data-name');

                pdfIframe.src = viewUrl + '#toolbar=0&navpanes=0';
                viewerTitle.textContent = `預覽簡報: ${displayName}`;
                viewerWrapper.style.display = 'flex';

                viewerWrapper.scrollIntoView({ behavior: 'smooth', block: 'start' });
            });
        });

        if (closeViewerBtn) {
            closeViewerBtn.addEventListener('click', () => {
                viewerWrapper.style.display = 'none';
                pdfIframe.src = 'about:blank';
            });
        }
    }

    // ==========================================================================
    // 3. 管理者後台: 切換編輯面板
    // ==========================================================================
    const menuItems = document.querySelectorAll('.admin-menu-item');
    const editPanels = document.querySelectorAll('.admin-edit-panel');

    if (menuItems.length > 0 && editPanels.length > 0) {
        menuItems.forEach(item => {
            item.addEventListener('click', () => {
                const targetId = item.getAttribute('data-target');

                menuItems.forEach(i => i.classList.remove('active'));
                item.classList.add('active');

                editPanels.forEach(p => p.classList.remove('active'));
                const targetPanel = document.getElementById(targetId);
                if (targetPanel) {
                    targetPanel.classList.add('active');
                }
            });
        });
    }

    // ==========================================================================
    // 4. 管理者後台: 即時圖片上傳預覽
    // ==========================================================================
    const imageInputs = document.querySelectorAll('.image-upload-input');
    imageInputs.forEach(input => {
        input.addEventListener('change', (e) => {
            const file = e.target.files[0];
            const productId = e.target.getAttribute('data-product-id');
            const previewImg = document.getElementById(`preview-img-${productId}`);

            if (file && previewImg) {
                if (!file.type.startsWith('image/')) {
                    alert('請選擇圖片檔案！');
                    e.target.value = '';
                    return;
                }
                previewImg.src = URL.createObjectURL(file);
            }
        });
    });

    // ==========================================================================
    // 5. 管理者後台: 動態規格欄位新增與刪除
    // ==========================================================================
    document.addEventListener('click', (e) => {
        // 刪除規格行
        const removeBtn = e.target.closest('.btn-remove-spec');
        if (removeBtn) {
            e.preventDefault();
            const row = removeBtn.closest('.spec-edit-row');
            if (row) row.remove();
        }

        // 新增規格行
        const addBtn = e.target.closest('.btn-add-spec');
        if (addBtn) {
            e.preventDefault();
            const productId = addBtn.getAttribute('data-product-id');
            const container = document.getElementById(`specs-container-${productId}`);
            if (container) {
                const newRow = document.createElement('div');
                newRow.className = 'spec-edit-row';
                newRow.innerHTML = `
                    <input type="text" name="spec_keys[]" class="form-control" placeholder="規格名稱 (例如: 藍牙版本)">
                    <input type="text" name="spec_values[]" class="form-control" placeholder="規格內容 (例如: 5.3)">
                    <button type="button" class="btn-remove-spec" title="刪除此規格">
                        <i class="fa-solid fa-trash"></i>
                    </button>
                `;
                container.appendChild(newRow);
            }
        }
    });
});
