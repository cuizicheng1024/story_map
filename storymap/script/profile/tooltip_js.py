from __future__ import annotations


def person_tooltip_js() -> str:
    return r"""
const personTooltipStripMd = (s) => String(s || '').replace(/\*\*/g, '').replace(/__/g, '').trim();
const personTooltipCleanTaglineText = (s) => String(s || '')
  .replace(/^\s*[-*•]\s*/u, '')
  .replace(/^\d+\.\s*/u, '')
  .replace(/^(?:人物)?短评\s*[：:]\s*/u, '')
  .trim();
const personTooltipStripOuterQuotes = (s) => {
  let t = String(s || '').trim();
  t = t.replace(/^[“"‘'「『]+/g, '').replace(/[”"’'」』]+$/g, '');
  return t.trim();
};
const personTooltipStripParenChars = (s) => String(s || '').replace(/[（）()]/g, '').trim();
const personTooltipFormatBirthplace = (ancient, modern) => {
  const a = personTooltipStripParenChars(String(ancient || '').trim());
  const m0 = personTooltipStripParenChars(String(modern || '').trim());
  const m = m0.replace(/^今\s*/g, '今').trim();
  if (a && m && a !== m) return `${a} · ${m}`;
  return a || m || '';
};
const personTooltipFormatYearLabel = (year) => {
  const num = Number(year);
  if (!Number.isFinite(num) || num === 0) return '';
  return num < 0 ? `前${Math.abs(Math.trunc(num))}年` : `${Math.trunc(num)}年`;
};
const personTooltipFormatYearRange = (birthYear, deathYear) => {
  const birth = personTooltipFormatYearLabel(birthYear);
  const death = personTooltipFormatYearLabel(deathYear);
  if (birth && death) return `${birth}-${death}`;
  return birth || death || '生卒待考';
};
const personTooltipUniqStrings = (items) => {
  const out = [];
  const seen = new Set();
  (Array.isArray(items) ? items : []).forEach((item) => {
    const text = String(item || '').trim();
    if (!text || seen.has(text)) return;
    seen.add(text);
    out.push(text);
  });
  return out;
};
const buildPersonTooltipModel = (node, options = {}) => {
  const name = String((node && (node.person || node.name)) || options.fallbackName || '相关人物').trim();
  const foreign = String(node?.foreign_name || node?.foreignName || '').trim();
  const aliases = personTooltipUniqStrings(Array.isArray(node?.aliases) ? node.aliases : [node?.aliases])
    .filter((item) => String(item || '').trim() && String(item || '').trim() !== name)
    .slice(0, Number.isFinite(Number(options.aliasLimit)) ? Math.max(0, Number(options.aliasLimit)) : 3);
  const displayName = foreign || name;
  const secondaryName = foreign && name && foreign !== name ? name : '';
  const roleLabel = String(node?.main_role_label || '').trim();
  const tags = personTooltipUniqStrings(Array.isArray(node?.domain_tags) ? node.domain_tags : []).slice(0, 4);
  const dynasty = String(node?.dynasty || '').trim();
  const birthplace = personTooltipFormatBirthplace(node?.birthplace, node?.birthplace_modern);
  const quote = personTooltipCleanTaglineText(personTooltipStripMd(String(node?.quote || '').trim()));
  const review = personTooltipCleanTaglineText(personTooltipStripMd(String(node?.review || '').trim()));
  const tagline = personTooltipStripOuterQuotes(review || quote);
  const rows = [
    { label: '生卒', value: personTooltipFormatYearRange(node?.birth_year, node?.death_year) },
  ];
  if (dynasty) rows.push({ label: '时代', value: dynasty });
  if (roleLabel) rows.push({ label: '身份', value: roleLabel });
  if (aliases.length) rows.push({ label: '别名', value: aliases.join(' / ') });
  if (tags.length) rows.push({ label: '领域', value: tags.join(' / ') });
  if (birthplace) rows.push({ label: '出生地', value: birthplace });
  return {
    name,
    displayName,
    secondaryName,
    rows,
    tagline,
    hasStory: node?.has_story !== false,
    badgeText: node?.has_story === false ? '暂未生成' : '',
  };
};
""".strip()
