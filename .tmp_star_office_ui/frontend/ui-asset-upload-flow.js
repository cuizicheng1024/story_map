window.STAR_OFFICE_ASSET_UPLOAD_FLOW_UI = (() => {
    function getUploadResultElement() {
        return document.getElementById('asset-upload-result');
    }

    function setUploadResultText(message) {
        const out = getUploadResultElement();
        if (out) {
            out.textContent = message;
        }
    }

    function isSpritesheetTarget(path) {
        const value = String(path || '').toLowerCase();
        if (!value) {
            return false;
        }
        return (
            value.includes('spritesheet') ||
            value.includes('sprite-sheet') ||
            value.includes('sheet') ||
            value.includes('anim') ||
            value.includes('grid')
        );
    }

    async function refreshAssetDrawerList({
        getSelectedPath,
        setAssetListData,
        buildSceneAssetItems,
        getSceneAssetItemsCount,
        renderAssetDrawerList,
        updateActiveAssetItem,
        applyScenePreview,
    }) {
        try {
            const selectedPath = getSelectedPath();
            const res = await fetch('/assets/list?t=' + Date.now(), { cache: 'no-store' });
            const data = await res.json();
            setAssetListData(data.items || []);

            buildSceneAssetItems();
            if (getSceneAssetItemsCount() === 0) {
                setTimeout(() => {
                    buildSceneAssetItems();
                    renderAssetDrawerList();
                }, 500);
            }

            renderAssetDrawerList();
            setUploadResultText(`已加载资产：${data.items?.length || 0} ｜ 场景抓取：${getSceneAssetItemsCount()}`);

            if (selectedPath) {
                updateActiveAssetItem(selectedPath);
                applyScenePreview(selectedPath);
            }
        } catch (error) {
            console.error('加载资产列表失败', error);
            setUploadResultText('❌ 资产加载失败，请点“刷新”重试');
        }
    }

    function bindDrawerFileMeta({
        getSelectedPath,
        getSelectedFile,
        applyScenePreview,
        renderSelectedAssetGuidance,
        clearUploadResult,
        updateAssetConfirmButtonState,
        translate,
        formatSizeHuman,
        mapAssetPathToSprite,
        getAssetDisplayName,
        getAssetHelpText,
        renderPendingUploadGuidance,
    }) {
        const input = document.getElementById('asset-upload-file');
        if (!input) {
            return;
        }
        input.onchange = () => {
            const file = getSelectedFile();
            const targetPath = getSelectedPath();
            if (!file) {
                if (targetPath) {
                    const inScene = !!applyScenePreview(targetPath);
                    renderSelectedAssetGuidance(targetPath, inScene);
                } else {
                    clearUploadResult();
                }
                updateAssetConfirmButtonState();
                return;
            }

            const targetLabel = targetPath || '-';
            const pendingText = `${translate('uploadPending')}：${file.name} ｜ ${formatSizeHuman(file.size)} ｜ ${translate('uploadTarget')}：${targetLabel}`;
            renderPendingUploadGuidance({
                pendingText,
                path: targetPath,
                inScene: targetPath ? !!mapAssetPathToSprite(targetPath) : null,
                getAssetDisplayName,
                getAssetHelpText,
                translate,
            });
            updateAssetConfirmButtonState();
        };
        updateAssetConfirmButtonState();
    }

    function openInlineAssetUploader() {
        const input = document.getElementById('asset-upload-file');
        if (input) {
            input.click();
        }
    }

    async function commitAssetUpdate({
        getSelectedPath,
        getSelectedFile,
    }) {
        const path = getSelectedPath();
        const file = getSelectedFile();
        if (!path) {
            setUploadResultText('请先选中一个资产路径');
            return false;
        }
        if (!file) {
            return true;
        }

        const fd = new FormData();
        fd.append('path', path);
        fd.append('backup', '1');
        fd.append('file', file);

        const nameLower = (file.name || '').toLowerCase();
        const isAnimInput = nameLower.endsWith('.gif') || nameLower.endsWith('.webp');
        if (isSpritesheetTarget(path)) {
            fd.append('auto_spritesheet', '1');
            if (isAnimInput) {
                fd.append('preserve_original', '1');
            } else {
                fd.append('frame_w', '64');
                fd.append('frame_h', '64');
                fd.append('preserve_original', '0');
            }
            fd.append('pixel_art', '1');
        }

        setUploadResultText('⏳ 正在上传并替换，请稍候...');
        let res;
        let data;
        try {
            res = await fetch('/assets/upload', { method: 'POST', body: fd });
            data = await res.json();
        } catch (error) {
            console.error('上传资产失败', error);
            setUploadResultText('❌ 更新失败：服务返回异常或网络中断，请稍后重试');
            return false;
        }
        if (!res.ok || !data || !data.ok) {
            setUploadResultText(`❌ 更新失败：${(data && data.msg) || res.status}`);
            return false;
        }

        if (data.converted) {
            const toType = data.converted.to || 'spritesheet';
            setUploadResultText(`✅ 已上传（动图→${toType}）：${data.path} ｜ ${data.converted.frames}帧 ${data.converted.frame_w}x${data.converted.frame_h}`);
        } else {
            setUploadResultText(`✅ 已上传：${data.path}`);
        }
        return true;
    }

    async function commitAndRefresh({
        commitAssetUpdate,
        hasSelectedFile,
        closeDrawer,
        reloadPage,
    }) {
        const hasFile = hasSelectedFile();
        const okUpload = await commitAssetUpdate();
        if (!okUpload) {
            return;
        }

        const out = getUploadResultElement();
        if (out) {
            if (hasFile) out.textContent += ' ｜ ✅ 已上传并刷新';
            else out.textContent = '✅ 已确认并刷新';
        }

        closeDrawer();
        setTimeout(() => reloadPage(), 400);
    }

    return Object.freeze({
        refreshAssetDrawerList,
        bindDrawerFileMeta,
        openInlineAssetUploader,
        commitAssetUpdate,
        commitAndRefresh,
    });
})();
