window.STAR_OFFICE_ASSET_GUIDANCE_UI = (() => {
    function getUploadResultElement() {
        return document.getElementById('asset-upload-result');
    }

    function clearUploadResult() {
        const out = getUploadResultElement();
        if (out) {
            out.innerHTML = '';
        }
    }

    function renderSelectedAssetGuidance({
        path,
        inScene = null,
        getAssetDisplayName,
        getAssetHelpText,
        translate,
    }) {
        const out = getUploadResultElement();
        if (!out) {
            return;
        }
        if (!path) {
            out.innerHTML = '';
            return;
        }
        const displayName = getAssetDisplayName(path);
        const hint = getAssetHelpText(path);
        const warn = inScene === false ? `⚠️ ${translate('assetHintNotInScene')}` : '';
        out.innerHTML = [
            `📌 ${displayName}（${path}）`,
            `💡 ${hint}`,
            warn,
        ]
            .filter(Boolean)
            .map((value) => `<p class="hint-p">${value}</p>`)
            .join('');
    }

    function renderPendingUploadGuidance({
        pendingText,
        path,
        inScene,
        getAssetDisplayName,
        getAssetHelpText,
        translate,
    }) {
        const out = getUploadResultElement();
        if (!out) {
            return;
        }
        if (!path) {
            out.innerHTML = `<p class="hint-p">${pendingText}</p>`;
            return;
        }
        const displayName = getAssetDisplayName(path);
        const hint = getAssetHelpText(path);
        const warn = inScene ? '' : `⚠️ ${translate('assetHintNotInScene')}`;
        out.innerHTML = [
            `<p class="hint-p">${pendingText}</p>`,
            `<p class="hint-p">📌 ${displayName}（${path}）</p>`,
            `<p class="hint-p">💡 ${hint}</p>`,
            warn ? `<p class="hint-p">${warn}</p>` : '',
        ]
            .filter(Boolean)
            .join('');
    }

    function setAssetActionState(canOperate) {
        const panel = document.getElementById('asset-upload-panel');
        const buttons = [
            document.getElementById('asset-commit-refresh-btn'),
            document.getElementById('asset-reset-default-btn'),
            document.getElementById('asset-restore-prev-btn'),
        ];
        if (panel) {
            panel.classList.toggle('active', canOperate);
        }
        buttons.forEach((button) => {
            if (!button) {
                return;
            }
            button.disabled = !canOperate;
            button.style.opacity = canOperate ? '1' : '.55';
        });
    }

    return Object.freeze({
        clearUploadResult,
        renderSelectedAssetGuidance,
        renderPendingUploadGuidance,
        setAssetActionState,
    });
})();
