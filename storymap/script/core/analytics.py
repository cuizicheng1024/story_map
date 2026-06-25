from __future__ import annotations

import json
import os
from typing import Dict, Optional


DEFAULT_VOLCENGINE_APM_AID = "1002542"


def first_env(*names: str) -> str:
    for name in names:
        value = os.getenv(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _google_analytics_head_html() -> str:
    measurement_id = first_env("MAP_STORY_GA_MEASUREMENT_ID", "GA_MEASUREMENT_ID")
    if not measurement_id:
        return ""
    quoted_id = json.dumps(measurement_id, ensure_ascii=False)
    return (
        f'<script async src="https://www.googletagmanager.com/gtag/js?id={measurement_id}"></script>'
        "<script>"
        "window.dataLayer=window.dataLayer||[];"
        "function gtag(){dataLayer.push(arguments);}"
        "gtag('js', new Date());"
        f"gtag('config', {quoted_id});"
        "</script>"
    )


def _volcengine_apm_head_html(
    *,
    page_type: str,
    page_name: str = "",
    default_aid: str = DEFAULT_VOLCENGINE_APM_AID,
    extra_categories: Optional[Dict[str, str]] = None,
) -> str:
    token = first_env("MAP_STORY_VOLCENGINE_APM_TOKEN", "VOLCENGINE_APM_TOKEN")
    if not token:
        return ""
    aid = (
        first_env("MAP_STORY_VOLCENGINE_APM_AID", "VOLCENGINE_APM_AID")
        or str(default_aid or "").strip()
    )
    if not aid:
        return ""
    aid_literal = aid if str(aid).isdigit() else json.dumps(str(aid), ensure_ascii=False)
    env_name = first_env("MAP_STORY_VOLCENGINE_APM_ENV", "VOLCENGINE_APM_ENV", "MAP_STORY_ENV", "ENV")
    release_name = first_env(
        "MAP_STORY_VOLCENGINE_APM_RELEASE",
        "VOLCENGINE_APM_RELEASE",
        "STORYMAP_BUILD_VERSION",
        "GITHUB_SHA",
    )
    custom_categories = {
        "page_type": str(page_type or "").strip() or "unknown",
        "page_name": str(page_name or "").strip(),
        "site_name": "map_story",
    }
    for key, value in (extra_categories or {}).items():
        normalized_key = str(key or "").strip()
        normalized_value = str(value or "").strip()
        if normalized_key and normalized_value:
            custom_categories[normalized_key] = normalized_value
    init_payload = {
        "aid": aid_literal,
        "token": json.dumps(token, ensure_ascii=False),
        "env": json.dumps(env_name, ensure_ascii=False) if env_name else None,
        "release": json.dumps(release_name, ensure_ascii=False) if release_name else None,
    }
    init_items = [f"aid:{init_payload['aid']}", f"token:{init_payload['token']}", "pid: window.location.pathname"]
    if init_payload["env"] is not None:
        init_items.append(f"env:{init_payload['env']}")
    if init_payload["release"] is not None:
        init_items.append(f"release:{init_payload['release']}")
    categories_literal = json.dumps(custom_categories, ensure_ascii=False)
    return (
        "<script>"
        "(function(n,e,r,t,a,o,s,i,c,l,f,m,p,u){"
        'o="precollect";s="getAttribute";i="addEventListener";c="PerformanceObserver";'
        "l=function(e){f=[].slice.call(arguments);f.push(Date.now(),location.href);(e==o?l.p.a:l.q).push(f)};"
        'l.q=[];l.p={a:[]};n[a]=l;m=document.createElement("script");m.src=r+"?aid="+t+"&globalName="+a;'
        'm.crossOrigin="anonymous";e.getElementsByTagName("head")[0].appendChild(m);'
        "if(i in n){"
        "l.pcErr=function(e){e=e||n.event;p=e.target||e.srcElement;"
        'if(p instanceof Element||p instanceof HTMLElement){n[a](o,"st",{tagName:p.tagName,url:p[s]("href")||p[s]("src")});}'
        'else{n[a](o,"err",e.error||e.message)}};'
        'l.pcRej=function(e){e=e||n.event;n[a](o,"reject",e.reason||e.detail&&e.detail.reason)};'
        'n[i]("error",l.pcErr,true);n[i]("unhandledrejection",l.pcRej,true)}'
        'if("PerformanceLongTaskTiming"in n){u=l.pp={entries:[]};u.observer=new PerformanceObserver(function(e){u.entries=u.entries.concat(e.getEntries())});u.observer.observe({entryTypes:["longtask"]})}'
        f'}})(window,document,"https://apm.volccdn.com/mars-web/apmplus/web/browser.cn.js",{aid_literal},"apmPlus");'
        "</script>"
        "<script>"
        "window.apmPlus('init',{" + ",".join(init_items) + "});"
        "window.apmPlus('start');"
        "window.apmPlus('sendEvent', {"
        "name:'story_map_page_open',"
        f"categories:Object.assign({categories_literal},{{path:window.location.pathname,hostname:window.location.hostname}})"
        "});"
        "</script>"
    )


def analytics_head_html(
    *,
    page_type: str,
    page_name: str = "",
    default_volcengine_aid: str = DEFAULT_VOLCENGINE_APM_AID,
    extra_categories: Optional[Dict[str, str]] = None,
) -> str:
    parts = [
        _google_analytics_head_html(),
        _volcengine_apm_head_html(
            page_type=page_type,
            page_name=page_name,
            default_aid=default_volcengine_aid,
            extra_categories=extra_categories,
        ),
    ]
    return "".join(part for part in parts if part)
