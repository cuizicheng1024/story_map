window.STAR_OFFICE_LANGUAGE_UI = (() => {
    const textBindings = Object.freeze([
        ['control-bar-title', 'controlTitle'],
        ['btn-state-idle', 'btnIdle'],
        ['btn-state-writing', 'btnWork'],
        ['btn-state-syncing', 'btnSync'],
        ['btn-state-error', 'btnError'],
        ['btn-open-drawer', 'btnDecor'],
        ['btn-close-drawer', 'drawerClose'],
        ['btn-move-house', 'btnMove'],
        ['btn-back-home', 'btnHome'],
        ['btn-back-last-bg', 'btnHomeLast'],
        ['btn-favorite-home', 'btnHomeFavorite'],
        ['asset-home-favorites-title', 'homeFavTitle'],
        ['speed-mode-label', 'speedModeLabel'],
        ['speed-fast-btn', 'speedFast'],
        ['speed-quality-btn', 'speedQuality'],
        ['gemini-panel-summary', 'geminiPanelTitle'],
        ['gemini-config-hint', 'geminiHint'],
        ['gemini-api-doc-link', 'geminiApiDoc'],
        ['btn-save-gemini-key', 'geminiSaveKey'],
        ['asset-choose-btn', 'chooseImage'],
        ['asset-commit-refresh-btn', 'confirmUpload'],
        ['asset-reset-default-btn', 'resetToDefault'],
        ['asset-restore-prev-btn', 'restorePrevAsset'],
        ['memo-title', 'memoTitle'],
        ['guest-agent-panel-title', 'guestTitle'],
    ]);

    const placeholderBindings = Object.freeze([
        ['asset-pass-input', 'authPlaceholder'],
        ['asset-broker-prompt', 'brokerPromptPh'],
        ['gemini-api-key-input', 'geminiInputPh'],
        ['asset-search', 'searchPlaceholder'],
    ]);

    const selectorTextBindings = Object.freeze([
        ['#asset-drawer-header span', 'drawerTitle'],
        ['#asset-auth-gate .asset-preview-title', 'authTitle'],
        ['#asset-auth-gate .asset-toolbar button', 'authVerify'],
        ['#asset-broker-row .btn-broker', 'btnBroker'],
        ['#asset-broker-row .btn-diy', 'btnDIY'],
        ['#asset-broker-panel .asset-sub', 'brokerHint'],
        ['#asset-broker-actions button', 'btnBrokerGo'],
    ]);

    const langButtons = Object.freeze([
        { id: 'lang-btn-en', lang: 'en' },
        { id: 'lang-btn-jp', lang: 'ja' },
        { id: 'lang-btn-cn', lang: 'zh' },
    ]);

    function applyIdTextBindings(translate) {
        textBindings.forEach(([id, key]) => {
            const el = document.getElementById(id);
            if (el) {
                el.textContent = translate(key);
            }
        });
    }

    function applyIdPlaceholderBindings(translate) {
        placeholderBindings.forEach(([id, key]) => {
            const el = document.getElementById(id);
            if (el) {
                el.placeholder = translate(key);
            }
        });
    }

    function applySelectorTextBindings(translate) {
        selectorTextBindings.forEach(([selector, key]) => {
            const el = document.querySelector(selector);
            if (el) {
                el.textContent = translate(key);
            }
        });
    }

    function applyLangButtonState(currentLang) {
        langButtons.forEach(({ id, lang }) => {
            const el = document.getElementById(id);
            if (!el) {
                return;
            }
            const active = currentLang === lang;
            el.style.background = active ? '#22c55e' : '#333';
            el.style.borderColor = active ? '#22c55e' : '#333';
            el.style.color = '#fff';
        });
    }

    return Object.freeze({
        textBindings,
        placeholderBindings,
        selectorTextBindings,
        langButtons,
        applyIdTextBindings,
        applyIdPlaceholderBindings,
        applySelectorTextBindings,
        applyLangButtonState,
    });
})();
