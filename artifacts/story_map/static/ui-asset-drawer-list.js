window.STAR_OFFICE_ASSET_DRAWER_LIST_UI = (() => {
    let assetThumbTimers = [];

    function canvasIdForPath(path) {
        return `asset-thumb-canvas-${(path || '').replace(/[^a-zA-Z0-9]/g, '_')}`;
    }

    function escapePathForSingleQuote(path) {
        return String(path || '').replace(/'/g, "\\'");
    }

    function clearAssetThumbTimers() {
        assetThumbTimers.forEach((timer) => clearInterval(timer));
        assetThumbTimers = [];
    }

    function inferSpritesheetFrameMetaByPath(path) {
        const value = (path || '').toLowerCase();
        if (!value) {
            return null;
        }
        if (
            value.includes('spritesheet') ||
            value.includes('sprite-sheet') ||
            value.includes('sheet') ||
            value.includes('anim') ||
            value.includes('grid')
        ) {
            return { w: null, h: null };
        }
        return null;
    }

    function getSpritesheetFrameMeta(item) {
        const inferred = inferSpritesheetFrameMetaByPath(item?.path || '');
        if (!inferred) {
            return null;
        }
        return { w: null, h: null, isSheet: true };
    }

    function guessThumbFrameSize(fullW, fullH, path = '') {
        const value = (path || '').toLowerCase();
        const hints = [
            [/star-working-spritesheet-grid\.webp$/, 300, 300],
            [/star-idle-v5\.(webp|png)$/, 256, 256],
            [/sync-animation-v3-grid\.webp$/, 256, 256],
            [/error-bug-spritesheet-grid\.webp$/, 220, 220],
            [/flowers-bloom-v2\.webp$/, 128, 128],
            [/plants-spritesheet\.webp$/, 160, 160],
        ];
        for (const [re, fw, fh] of hints) {
            if (re.test(value) && fullW % fw === 0 && fullH % fh === 0) {
                return { fw, fh };
            }
        }

        const divisors = (n) => {
            const values = [];
            for (let i = 1; i * i <= n; i += 1) {
                if (n % i === 0) {
                    values.push(i);
                    if (i * i !== n) {
                        values.push(n / i);
                    }
                }
            }
            return values.sort((a, b) => a - b);
        };

        const widthCandidates = divisors(fullW).filter((v) => v >= 48 && v <= 512);
        const heightCandidates = divisors(fullH).filter((v) => v >= 48 && v <= 512);
        let best = null;
        for (const fw of widthCandidates) {
            for (const fh of heightCandidates) {
                const cols = fullW / fw;
                const rows = fullH / fh;
                if (!Number.isInteger(cols) || !Number.isInteger(rows)) {
                    continue;
                }
                const frames = cols * rows;
                if (frames <= 1 || cols < 2 || rows < 1) {
                    continue;
                }
                let score = 0;
                if (cols === 8) score += 120;
                else if (cols >= 4 && cols <= 10) score += 45;
                if (rows >= 1 && rows <= 10) score += 25;
                score += Math.min(frames, 120) * 0.8;
                score -= Math.abs(fw - fh) * 0.12;
                if (fw === fullW || fh === fullH) score -= 80;
                if (!best || score > best.score) {
                    best = { fw, fh, score };
                }
            }
        }
        return best ? { fw: best.fw, fh: best.fh } : null;
    }

    function tryAnimateAssetThumb(item) {
        if (!item) {
            return;
        }
        const canvas = document.getElementById(canvasIdForPath(item.path || ''));
        if (!canvas) {
            return;
        }
        const ctx = canvas.getContext('2d');
        if (!ctx) {
            return;
        }

        const img = new Image();
        img.onload = () => {
            const fullW = img.naturalWidth || img.width;
            const fullH = img.naturalHeight || img.height;
            const meta = getSpritesheetFrameMeta(item);
            if (!meta) {
                return;
            }
            const guessed = guessThumbFrameSize(fullW, fullH, item?.path || '');
            if (!guessed) {
                return;
            }
            const fw = guessed.fw;
            const fh = guessed.fh;
            const cols = Math.floor(fullW / fw);
            const rows = Math.floor(fullH / fh);
            const frames = cols * rows;
            if (cols < 1 || rows < 1 || frames <= 1) {
                return;
            }

            let idx = 0;
            const draw = () => {
                const cx = (idx % cols) * fw;
                const cy = Math.floor(idx / cols) * fh;
                ctx.clearRect(0, 0, canvas.width, canvas.height);
                ctx.imageSmoothingEnabled = false;
                ctx.drawImage(img, cx, cy, fw, fh, 0, 0, canvas.width, canvas.height);
                idx = (idx + 1) % frames;
            };
            draw();
            assetThumbTimers.push(setInterval(draw, 120));
        };
        img.src = `/static/${item.path}?t=${Date.now()}`;
    }

    function isAssetHidden(hiddenAssetPaths, path) {
        return hiddenAssetPaths.has(path || '');
    }

    function setAssetVisible({ path, visible, hiddenAssetPaths, resolveSprite }) {
        const value = (path || '').trim();
        if (!value) {
            return;
        }
        if (visible) hiddenAssetPaths.delete(value);
        else hiddenAssetPaths.add(value);

        const sprite = resolveSprite(value);
        if (sprite && sprite.setVisible) {
            sprite.setVisible(!!visible);
        }
    }

    function toggleAssetVisibility({
        path,
        event,
        hiddenAssetPaths,
        resolveSprite,
        rerender,
        setStatusText,
        selectedPath,
        clearAssetSelectionUI,
        applyScenePreview,
    }) {
        if (event && event.stopPropagation) {
            event.stopPropagation();
        }
        const value = (path || '').trim();
        if (!value) {
            return;
        }
        const nextVisible = isAssetHidden(hiddenAssetPaths, value);
        setAssetVisible({
            path: value,
            visible: nextVisible,
            hiddenAssetPaths,
            resolveSprite,
        });
        rerender();
        setStatusText(nextVisible ? `✅ 已显示：${value}` : `🙈 已隐藏：${value}`);
        if (selectedPath === value) {
            if (!nextVisible) clearAssetSelectionUI();
            else applyScenePreview(value);
        }
    }

    function assetRank(path = '') {
        const value = (path || '').toLowerCase();
        const statePriority = [
            'star-idle-v5.png',
            'star-working-spritesheet-grid.webp',
            'sync-animation-v3-grid.webp',
            'error-bug-spritesheet-grid.webp',
        ];
        const idx = statePriority.findIndex((item) => value.endsWith(item));
        if (idx >= 0) {
            return idx;
        }
        if (value.includes('/btn-') || value.includes('btn-') || value.includes('button')) {
            return 1000;
        }
        if (value.includes('guest_anim_')) {
            return 999;
        }
        return 100;
    }

    function renderAssetDrawerList({
        assetListData,
        selectedPath,
        getAssetDisplayName,
        hiddenAssetPaths,
        searchQuery,
        onSelectName = 'selectAssetInDrawer',
        onToggleName = 'toggleAssetVisibility',
    }) {
        const list = document.getElementById('asset-list');
        if (!list) {
            return;
        }

        const rows = assetListData
            .map((item) => {
                const displayName = getAssetDisplayName(item.path || '');
                return {
                    ...item,
                    key: String(item.key || displayName || '').toLowerCase(),
                };
            })
            .filter((item) => {
                if (!searchQuery) {
                    return true;
                }
                return (
                    (item.path || '').toLowerCase().includes(searchQuery) ||
                    (item.key || '').toLowerCase().includes(searchQuery)
                );
            })
            .sort((a, b) => {
                const ra = assetRank(a.path);
                const rb = assetRank(b.path);
                if (ra !== rb) {
                    return ra - rb;
                }
                return (a.path || '').localeCompare(b.path || '');
            });

        clearAssetThumbTimers();

        if (rows.length === 0) {
            list.innerHTML = '<div class="asset-sub" style="padding:8px">暂无资产（可点“刷新”重试）</div>';
            return;
        }

        list.innerHTML = rows
            .map((item) => {
                const active = selectedPath === item.path;
                const reso = item.width && item.height ? `${item.width}×${item.height}` : '-';
                const displayName = getAssetDisplayName(item.path || '');
                const hidden = isAssetHidden(hiddenAssetPaths, item.path);
                const visEmoji = hidden ? '🙈' : '👀';
                const escapedPath = escapePathForSingleQuote(item.path || '');
                return `<div class="asset-item ${active ? 'active' : ''}" data-path="${item.path}" onclick="${onSelectName}('${escapedPath}')">
                    <canvas id="${canvasIdForPath(item.path || '')}" class="asset-thumb" width="56" height="56"></canvas>
                    <div class="asset-meta">
                        <div class="asset-path">${item.path}</div>
                        <div class="asset-sub">${displayName} ｜ ${reso}${hidden ? ' ｜ 已隐藏' : ''}</div>
                    </div>
                    <button class="asset-vis-btn" onclick="${onToggleName}('${escapedPath}', event)">${visEmoji}</button>
                </div>`;
            })
            .join('');

        rows.forEach((item) => {
            const canvas = document.getElementById(canvasIdForPath(item.path || ''));
            if (!canvas) {
                return;
            }
            const ctx = canvas.getContext('2d');
            if (!ctx) {
                return;
            }
            const img = new Image();
            img.onload = () => {
                ctx.clearRect(0, 0, canvas.width, canvas.height);
                ctx.imageSmoothingEnabled = false;
                ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
                tryAnimateAssetThumb(item);
            };
            img.src = `/static/${item.path}?t=${Date.now()}`;
        });
    }

    return Object.freeze({
        clearAssetThumbTimers,
        isAssetHidden,
        setAssetVisible,
        toggleAssetVisibility,
        renderAssetDrawerList,
    });
})();
