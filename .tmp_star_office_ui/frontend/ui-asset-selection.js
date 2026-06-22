window.STAR_OFFICE_ASSET_SELECTION_UI = (() => {
    let drawerBackgroundBound = false;

    function clearSelectionVisual({ selectionBoxGraphics } = {}) {
        const highlight = document.getElementById('asset-highlight');
        if (highlight) {
            highlight.style.display = 'none';
        }
        if (selectionBoxGraphics) {
            selectionBoxGraphics.setVisible(false);
        }
    }

    function updateActiveAssetItem(path) {
        document.querySelectorAll('#asset-list .asset-item').forEach((element) => {
            const itemPath = element.getAttribute('data-path');
            element.classList.toggle('active', itemPath === path);
        });
    }

    function selectAssetInDrawer({
        path,
        selectedPath,
        assetListData,
        clearAssetSelection,
        setSelectedAssetInfo,
        applyScenePreview,
        renderSelectedAssetGuidance,
        updateAssetConfirmButtonState,
    }) {
        if (selectedPath && selectedPath === path) {
            clearAssetSelection(true);
            return;
        }
        const nextSelected = assetListData.find((item) => item.path === path) || null;
        setSelectedAssetInfo(nextSelected);
        updateActiveAssetItem(path);
        const inScene = applyScenePreview(path);
        renderSelectedAssetGuidance(path, inScene);
        updateAssetConfirmButtonState();
    }

    function bindDrawerBackgroundDeselect({
        canDeselect,
        clearAssetSelection,
    }) {
        if (drawerBackgroundBound) {
            return;
        }
        drawerBackgroundBound = true;
        const body = document.getElementById('asset-drawer-body');
        if (!body) {
            return;
        }
        body.addEventListener('click', (event) => {
            if (!canDeselect()) {
                return;
            }
            const keep = event.target.closest(
                '.asset-item, .asset-toolbar, #asset-upload-panel, #asset-move-panel, button, input, textarea, label, canvas'
            );
            if (keep) {
                return;
            }
            clearAssetSelection(true);
        });
    }

    return Object.freeze({
        clearSelectionVisual,
        updateActiveAssetItem,
        selectAssetInDrawer,
        bindDrawerBackgroundDeselect,
    });
})();
