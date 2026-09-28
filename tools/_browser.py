# -*- coding: utf-8 -*-
"""无头浏览器验收：注入探针 → 跑场景 → 回传运行时数值。

用法（在仓库根目录下）：
    python tools/_browser.py home lesson exopen review spaced records exstale narrow430 narrow768
    python tools/_report.py        # 把结果压成通过/失败清单

路径一律从本文件位置推出来，clone 到任何地方都能直接跑。

设计要点（都是踩过坑之后才定下来的）：
1. 结果用 base64 编码后塞进注释节点。纯 A-Za-z0-9+/= 不可能是 HTML 特殊字符，
   比用 `@@KEY=VAL@@` 之类的裸标记安全得多——之前就是被内容里的 @ 截断过。
2. 每记录一个指标就立刻 re-emit，即使探针中途抛错，前面的数据也能拿到。
3. 错误钩子注入到 <head>，必须早于应用脚本，否则初始化期的报错抓不到。
"""
import base64
import json
import os
import re
import subprocess
import sys
import traceback
import uuid
from datetime import date, timedelta
from pathlib import Path

B = Path(__file__).resolve().parent
ROOT = B.parent
SRC = ROOT / "python-学习工作台.html"
CHROME = os.environ.get("CHROME_PATH") or next(
    (p for p in (
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium",
    ) if os.path.exists(p)),
    "chrome",
)

# ------------------------------------------------------------------ 注入片段
ERR_HOOK = (
    "<script>window.__errs=[];(function(){"
    "function push(s){window.__errs.push(s);try{"
    "var b=document.getElementById('__errbox');"
    "if(!b){b=document.createElement('div');b.id='__errbox';"
    "b.style.cssText='position:absolute;left:-99999px;top:0';"
    "(document.body||document.documentElement).appendChild(b);}"
    "b.textContent+=' ||| '+s;}catch(e){}}"
    "window.addEventListener('error',function(e){"
    "push('ERR:'+(e.message||'')+'@L'+e.lineno)},true);"
    "window.addEventListener('unhandledrejection',function(e){"
    "push('REJ:'+String(e.reason))});"
    "var ce=console.error,cw=console.warn;"
    "console.error=function(){push('CE:'+[].join.call(arguments,' '));"
    "return ce.apply(console,arguments)};"
    "console.warn=function(){push('CW:'+[].join.call(arguments,' '));"
    "return cw.apply(console,arguments)};})();</script>\n"
)

BASE = r"""(async function(){
var OUT=document.createComment('PENDING');
document.documentElement.appendChild(OUT);
// 除了注释，再镜像一份到隐藏节点：注释万一被丢弃，还有第二条取证路径
var MIR=document.createElement('div');
MIR.id='__probe_out';
MIR.style.cssText='position:absolute;left:-99999px;top:0';
document.documentElement.appendChild(MIR);
var M={};
function emit(){
  var s=JSON.stringify(M);
  var bytes=new TextEncoder().encode(s), bin='';
  for(var i=0;i<bytes.length;i++) bin+=String.fromCharCode(bytes[i]);
  var b64=btoa(bin);
  OUT.textContent='PROBE_BEGIN'+b64+'PROBE_END';
  MIR.textContent='PROBEB64'+b64+'PROBEEND';
}
var P={
  p:function(k,v){M[k]=v;emit();},
  wait:function(ms){return new Promise(function(r){setTimeout(r,ms)})},
  ready:function(sel,cap){
    cap=cap||5000;
    return new Promise(function(res){
      var t0=Date.now();
      (function loop(){
        if(document.querySelector(sel))return res(true);
        if(Date.now()-t0>cap)return res(false);
        setTimeout(loop,50);
      })();
    });
  },
  all:function(s,r){return Array.prototype.slice.call((r||document).querySelectorAll(s))},
  ob:function(s,r){return (r||document).querySelector(s)},
  // 轮询等待：FileReader 之类是真实异步 I/O，虚拟时钟推不动它，
  // 固定 wait 会误判成「没生效」。多让出几轮事件循环才靠得住。
  until:function(fn,tries,gap){
    tries=tries||400;gap=gap||40;
    return new Promise(function(res){
      var n=0;
      (function loop(){
        var v=false;
        try{v=!!fn()}catch(e){}
        if(v)return res(true);
        if(++n>=tries)return res(false);
        setTimeout(loop,gap);
      })();
    });
  },
  click:function(el){
    if(!el){return false}
    ['mousedown','mouseup'].forEach(function(t){
      el.dispatchEvent(new MouseEvent(t,{bubbles:true,cancelable:true}))});
    el.click();return true;
  },
  key:function(k,shift){
    document.dispatchEvent(new KeyboardEvent('keydown',{
      key:k,shiftKey:!!shift,bubbles:true,cancelable:true}));
  },
  blur:function(){ if(document.activeElement&&document.activeElement.blur)document.activeElement.blur(); },
  cs:function(el,prop){return el?getComputedStyle(el)[prop]:''},
  geo:function(sel){
    var e=document.querySelector(sel);if(!e)return 'none';
    var r=e.getBoundingClientRect();
    return [Math.round(r.x),Math.round(r.y),Math.round(r.width),Math.round(r.height)].join(',');
  },
  // 溢出元素：固定定位容器、可横向滚动容器内的内容、零尺寸元素都不算溢出，容差 1.5px
  // .skip / .sr 是刻意移出视口的无障碍元素；关闭状态的抽屉整棵子树也不算溢出
  // 代码块 .hl pre 是 overflow-x:auto，内容超出换行宽度属于设计预期，不该报缺陷
  ovf:function(){
    var vw=document.documentElement.clientWidth, bad=[];
    var hosts=[], scrollers=[];
    P.all('body *').forEach(function(e){
      var cs=getComputedStyle(e);
      if(cs.position==='fixed')hosts.push(e);
      if(cs.overflowX==='auto'||cs.overflowX==='scroll')scrollers.push(e);
    });
    P.all('body *').forEach(function(e){
      var r=e.getBoundingClientRect();
      if(!r.width||!r.height)return;
      if(e.closest('.skip,.sr'))return;
      if(getComputedStyle(e).position==='fixed')return;
      if(hosts.some(function(h){return h!==e&&h.contains(e)}))return;
      if(scrollers.some(function(s){return s!==e&&s.contains(e)}))return;
      if(r.right>vw+1.5||r.left<-1.5){
        var cls=(typeof e.className==='string'&&e.className.trim())
          ? '.'+e.className.trim().split(/\s+/)[0] : '';
        bad.push(e.tagName.toLowerCase()+(e.id?'#'+e.id:'')+cls
          +'@'+Math.round(r.left)+'..'+Math.round(r.right));
      }
    });
    return bad.slice(0,12);
  },
  // 触摸目标：只看真正的控件，正文里的行内链接不算
  small:function(){
    var sel='button,.btn,.rate-btn,.rv-go,.tab,.nav-item,.nav-home,label.hw-tick,'
      +'summary,input[type=checkbox],a.stat,select';
    var bad=[];
    P.all(sel).forEach(function(e){
      var r=e.getBoundingClientRect();
      if(!r.width||!r.height)return;
      var st=getComputedStyle(e);
      if(st.visibility==='hidden'||st.display==='none')return;
      if(r.height<43.5||r.width<43.5){
        bad.push(e.tagName.toLowerCase()+(e.id?'#'+e.id:'')
          +(e.className&&typeof e.className==='string'&&e.className.trim()
            ?'.'+e.className.trim().split(/\s+/)[0]:'')
          +':'+Math.round(r.width)+'x'+Math.round(r.height));
      }
    });
    return bad.slice(0,20);
  },
  // 颜色解析：color(srgb r g b / a) 的分量是 0-1，rgba() 是 0-255，必须分开处理
  rgbOf:function(c){
    var m=String(c).match(/-?[\d.]+/g);
    if(!m)return null;
    var k=/^color\(/.test(String(c))?255:1;
    return m.slice(0,3).map(function(x){return parseFloat(x)*k});
  },
  alphaOf:function(c){
    var m=String(c).match(/-?[\d.]+/g);
    if(!m)return 1;
    if(/^color\(/.test(String(c))||/^rgba\(/.test(String(c)))
      return m.length>3?parseFloat(m[3]):1;
    return 1;
  },
  firstStopOf:function(img){
    var m=String(img||'').match(/(rgba?\([^)]*\)|color\([^)]*\))/);
    return m?m[1]:null;
  },
  lumOf:function(rgb){
    if(!rgb)return 0;
    var v=rgb.map(function(x){
      x=Math.max(0,Math.min(255,x))/255;
      return x<=0.03928?x/12.92:Math.pow((x+0.055)/1.055,2.4)});
    return 0.2126*v[0]+0.7152*v[1]+0.0722*v[2];
  },
  blend:function(base,over,a){
    return [0,1,2].map(function(i){return over[i]*a+base[i]*(1-a)});
  },
  // 把祖先链上的半透明背景真正合成出来，别一遇到 alpha<1 就直接跳到底色
  bgOf:function(el){
    var chain=[],e=el;
    while(e&&e!==document.documentElement){
      var st=getComputedStyle(e);
      var c=st.backgroundColor,a=P.alphaOf(c);
      if(a>0.004){
        chain.push({c:c,a:a});
        if(a>=0.999)break;
      }else if(/gradient/.test(String(st.backgroundImage))){
        var s=P.firstStopOf(st.backgroundImage);
        if(s){chain.push({c:s,a:P.alphaOf(s)});break}
      }
      e=e.parentElement;
    }
    var base=[255,255,255];
    for(var i=chain.length-1;i>=0;i--){
      var rgb=P.rgbOf(chain[i].c);
      if(rgb)base=P.blend(base,rgb,chain[i].a);
    }
    return base;
  },
  contrast:function(sel){
    var e=document.querySelector(sel);if(!e)return 'none';
    var a=P.lumOf(P.rgbOf(getComputedStyle(e).color)),b=P.lumOf(P.bgOf(e));
    if(a<b){var t=a;a=b;b=t}
    return Math.round(((a+0.05)/(b+0.05))*100)/100;
  },
  pseudo:function(el,name,prop){ return getComputedStyle(el,name)[prop]; },
  // 全页扫文字对比度：只看叶子节点，大字号按 3:1；同类问题聚合计数，避免刷屏
  contrastSweep:function(){
    var seen={},res=[];
    P.all('body *').forEach(function(e){
      if(e.children.length)return;
      var t=(e.textContent||'').trim();
      if(!t)return;
      var r=e.getBoundingClientRect();
      if(!r.width||!r.height)return;
      var st=getComputedStyle(e);
      if(st.visibility==='hidden'||st.display==='none'||+st.opacity<0.5)return;
      if(e.closest('.skip,.sr'))return;
      var fs=parseFloat(st.fontSize),fw=+st.fontWeight||400;
      var need=((fs>=24)||(fs>=18.66&&fw>=700))?3:4.5;
      var a=P.lumOf(P.rgbOf(st.color)),b=P.lumOf(P.bgOf(e));
      if(a<b){var t3=a;a=b;b=t3}
      var cr=Math.round(((a+0.05)/(b+0.05))*100)/100;
      if(cr<need){
        var cls=(typeof e.className==='string'&&e.className.trim())
          ?'.'+e.className.trim().split(/\s+/)[0]:'';
        var key=e.tagName.toLowerCase()+(e.id?'#'+e.id:'')+cls
          +' '+fs+'px/'+fw+' '+cr+':'+need;
        if(seen[key]){seen[key].n++;return}
        var o={n:1,s:key,txt:t.slice(0,14)};
        seen[key]=o;res.push(o);
      }
    });
    return res.sort(function(a,b){return b.n-a.n}).slice(0,30)
      .map(function(o){return o.s+(o.n>1?' x'+o.n:'')+' "'+o.txt+'"'});
  },
  errs:function(){return (window.__errs||[]).slice(0,6)}
};

// 关掉过渡与动画，几何量才是稳定的最终值
var kill=document.createElement('style');
kill.textContent='*,*::before,*::after{transition:none!important;'
  +'animation-duration:0.001s!important;animation-iteration-count:1!important;'
  +'scroll-behavior:auto!important}';
document.head.appendChild(kill);

// 先报平安再干活：探针要是挂了，至少能知道它是启动过的
P.p('__ALIVE',1);
P.p('__HASH',location.hash);
P.p('__CONTENT_CHILD',(document.querySelector('#contentRoot')||{}).childElementCount);
P.p('__BOOT_ERR',(window.__errs||[]).slice(0,6));

// 整段场景包在 try 里，异常也要回传，否则只能看到一个空结果
try{
"""

TAIL = r"""
}catch(e){
  P.p('__PROBE_ERROR',String((e&&e.stack)||e).slice(0,600));
}
P.p('__ERRS_N',(window.__errs||[]).length);
P.p('__ERRS',P.errs());
P.p('__DONE',1);
emit();
})();
"""

# ------------------------------------------------------------------ 场景脚本
HOME_UI = r"""
await P.ready('.hero');
await P.wait(500);

P.p('VW',document.documentElement.clientWidth);
P.p('NAV_TOP',P.all('.nav .nav-home').length);
P.p('NAV_HREFS',P.all('.nav .nav-home').map(function(a){return a.getAttribute('href')}).join(' '));
P.p('BADGE_TXT',(P.ob('#reviewBadge')||{}).textContent||'');
P.p('BADGE_DISPLAY',P.cs(P.ob('#reviewBadge'),'display'));
P.p('HERO_STATS',P.all('.hero-stats > *').length);
P.p('HERO_STAT_LINKS',P.all('a.stat').map(function(a){return a.getAttribute('href')}).join(' '));
P.p('STAGE_CARDS',P.all('.stage-card').length);
P.p('MILE_N',P.all('.mile li').length);
P.p('FAQ_N',P.all('details.faq').length);
P.p('HERO_TABLES',P.all('.doc table').length);

// ---- 首页说明区的标题大纲 ----
// 缺陷史：`COURSE.home.map(s => s.html)` 只拼了正文、把 s.title 丢掉，于是
// README 的 7 个 `##` 标题全都不渲染，它们的 `###` 子节就以 h3 直接挂在
// 「四个阶段」底下——按标题跳读的人会以为「课程规模」属于「四个阶段」。
// 修好后把这里翻成闸门。注意：这个缺陷**不是**层级跳跃（h2 后面跟 h3 本来合法），
// 而是**标题整个丢了**，所以断言必须查"标题在不在、次序对不对"，查跳级是抓不住的。
var __docH2 = P.all('.doc h2').map(function(h){return h.textContent.trim()});
var __want  = (COURSE.home||[]).map(function(s){return (s.title||'').trim()});
P.p('DOC_H2_N',__docH2.length);
P.p('HOME_TITLES',__want.join('|'));
// 只比前 N 个：`.doc` 里还挂着模板自己的「里程碑自测」段头，它是 h2 但不在 README 里
P.p('DOC_H2_HEAD',__docH2.slice(0,__want.length).join('|'));
P.p('DOC_H2_MATCH',__docH2.slice(0,__want.length).join('|')===__want.join('|'));
// `.doc` 里出现的第一个标题必须是 h2（段的标题），而不是某个段的 h3 子节
P.p('DOC_FIRST_HEAD_IS_H2',(function(){
  var hs=P.all('.doc h2, .doc h3');
  return hs.length? (hs[0].tagName==='H2') : false;
})());
P.p('DOC_H2_BEFORE_H3',(function(){
  var hs=P.all('.doc h2, .doc h3'), seenH2=false, bad=0;
  hs.forEach(function(h){ if(h.tagName==='H2')seenH2=true; else if(!seenH2)bad++; });
  return bad;
})());
// 顺带的通例：整页只有一个 h1，且标题层级不跳档
P.p('HOME_H1_N',document.querySelectorAll('h1').length);
P.p('HOME_SKIP',(function(){
  var hs=[].slice.call(document.querySelectorAll('h1,h2,h3,h4,h5,h6')),bad=[];
  for(var i=1;i<hs.length;i++){
    var a=+hs[i-1].tagName[1], b=+hs[i].tagName[1];
    if(b>a+1) bad.push(a+'>'+b+':'+hs[i].textContent.trim().slice(0,16));
  }
  return bad.join(',');
})());

// ---- 快捷键：? 帮助面板 ----
P.key('?');
await P.wait(250);
P.p('HELP_OPEN',P.ob('#helpOverlay').dataset.open);
P.p('HELP_KEYS',P.all('#helpKeys li').length);
P.p('HELP_BODY_LOCK',document.body.style.overflow);
P.key('Escape');
await P.wait(200);
P.p('HELP_CLOSED',P.ob('#helpOverlay').dataset.open);

// ---- 快捷键：/ 搜索 ----
P.blur();
P.key('/');
await P.wait(250);
P.p('SEARCH_BY_SLASH',P.ob('#overlay').dataset.open);
P.p('FOCUS_IS_INPUT',document.activeElement===P.ob('#searchInput'));
var inp=P.ob('#searchInput');
inp.value='装饰器';inp.dispatchEvent(new Event('input',{bubbles:true}));
await P.wait(500);
P.p('SEARCH_N',P.all('.res').length);
P.p('SEARCH_TOP',(P.ob('.res b')||{}).textContent||'');
P.p('SEARCH_MARK',P.all('.res mark').length>0?'yes':'no');
P.key('Escape');
await P.wait(220);
P.p('SEARCH_CLOSED',P.ob('#overlay').dataset.open);
P.p('SEARCH_UNLOCK',document.body.style.overflow===''?'yes':'no');
P.p('FOCUS_BACK',document.activeElement===P.ob('#searchBtn'));

// ---- 快捷键：D 主题 ----
P.blur();
var t0=document.documentElement.dataset.theme;
P.key('d');
await P.wait(200);
var t1=document.documentElement.dataset.theme;
P.p('THEME_TOGGLE',t0+'->'+t1);
P.p('THEME_STORED',(JSON.parse(localStorage.getItem(__bench.KEY)||'{}').theme)||'');
P.p('DARK_BG',getComputedStyle(document.body).backgroundColor);
P.p('CT_SWEEP_DARK',P.contrastSweep());
P.key('d');
await P.wait(200);
P.p('THEME_BACK',document.documentElement.dataset.theme===t0?'yes':'no');

// ---- 在输入框里不该触发单键快捷键 ----
P.ob('#searchBtn').click();
await P.wait(300);
var t2=document.documentElement.dataset.theme;
P.ob('#searchInput').dispatchEvent(new KeyboardEvent('keydown',{key:'d',bubbles:true,cancelable:true}));
await P.wait(150);
P.p('TYPING_GUARD',document.documentElement.dataset.theme===t2?'ok':'LEAK');
P.key('Escape');
await P.wait(200);
P.blur();

// ---- 今日计划：空状态。四张卡都得在，但只该有「下一个知识点」亮着。
//      没活可干的那几张若还挂着箭头，就等于骗人点进去 ----
P.p('PLAN_CARDS',P.all('.today-card').length);
P.p('PLAN_KEYS',P.all('.today-card').map(function(a){return a.dataset.k}).join(','));
P.p('PLAN_ONLY_NEXT',(function(){
  var on=P.all('.today-card[data-on="1"]').map(function(a){return a.dataset.k});
  return on.length===1&&on[0]==='next'?'yes':'MISMATCH:'+on.join('|');
})());
P.p('PLAN_ARROW_MATCH',(function(){
  var bad=[];
  P.all('.today-card').forEach(function(a){
    var g=a.querySelector('.tc-go');
    var shown=!!g&&P.cs(g,'display')!=='none';
    if(shown!==(a.dataset.on==='1'))bad.push(a.dataset.k);
  });
  return bad.length?'MISMATCH:'+bad.join('|'):'yes';
})());
// 空工作台的欠债文案不能是"今天该复习 0 道"这种没话找话的说法
P.p('PLAN_EMPTY_NOTE',P.ob('[data-k="due"] .tc-note').textContent.indexOf('空着')>=0?'yes':'CHECK');

// ---- 布局 ----
P.p('NO_HSCROLL',document.documentElement.scrollWidth<=document.documentElement.clientWidth+1?'yes':'NO-BAD');
P.p('OVF',P.ovf());
P.p('SMALL',P.small());
P.p('MAIN_GEO',P.geo('.main'));
P.p('TOPBAR_GEO',P.geo('.topbar'));
P.p('GRID_COLS',P.cs(P.ob('.app'),'gridTemplateColumns'));
P.p('SCROLL_LOCKED',document.body.style.overflow===''?'no':'LOCKED');
P.p('BG_GRADIENT',String(P.pseudo(document.body,'::before','backgroundImage')).indexOf('gradient')>=0?'yes':'NO-BAD');
P.p('BG_NOISE',String(P.pseudo(document.body,'::after','backgroundImage')).indexOf('svg')>=0?'yes':'NO-BAD');
P.p('BG_NOT_WHITE',/^rgb\(25[0-5], 25[0-5], 25[0-5]\)$/.test(getComputedStyle(document.body).backgroundColor)?'NO-BAD':'ok');
P.p('CT_LEDE',P.contrast('.hero-lede'));
P.p('CT_STAT',P.contrast('.stat span'));
P.p('CT_SECHEAD',P.contrast('.section-head p'));
P.p('CT_SWEEP',P.contrastSweep());
"""

LESSON_UI = r"""
await P.ready('.lesson-body');
await P.wait(500);

var ds=P.all('details.answer');
P.p('TITLE',(P.ob('.lesson-head h1')||{}).textContent||'');
P.p('ANSWERS_N',ds.length);
P.p('RATE_BARS',P.all('.rate').length);
P.p('STATE_SLOTS',P.all('.ans-state').length);
P.p('STATE_EMPTY',P.all('.ans-state').filter(function(s){return !s.textContent}).length);
P.p('HINT',P.ob('.ans-hint')?P.cs(P.ob('.ans-hint'),'fontSize'):'none');
P.p('LANG_TAGS',P.all('.hl-lang').length);
P.p('COPY_BTNS',P.all('.hl-copy').length);
P.p('HW_N',P.all('ol.hw-list > li').length);
P.p('EX_GAUGE_BEFORE',(P.ob('#exTxt')||{}).textContent||'none');
P.p('ANSWER_MARK_ATTR',ds[0]?ds[0].dataset.mark:'none');

// ---- 标记「没写出来」 ----
ds[0].open=true;
await P.wait(200);
P.click(P.ob('.rate .rate-btn[data-m="-1"]'));
await P.wait(260);
P.p('MARK_AFTER_BAD',ds[0].dataset.mark);
P.p('STATE_TXT_BAD',(P.ob('.ans-state')||{}).textContent||'');
P.p('PRESSED_BAD',P.ob('.rate .rate-btn[data-m="-1"]').getAttribute('aria-pressed'));
P.p('BORDER_BAD',P.cs(ds[0],'borderTopColor'));
P.p('EX_GAUGE_AFTER',(P.ob('#exTxt')||{}).textContent||'none');
P.p('BADGE_AFTER_BAD',(P.ob('#reviewBadge')||{}).textContent||'');
P.p('BADGE_ZERO_ATTR',P.ob('#reviewBadge').dataset.zero);
var st1=JSON.parse(localStorage.getItem(__bench.KEY)||'{}');
P.p('STORED_EX',JSON.stringify(st1.ex||{}));
P.p('TOAST_BAD',(P.ob('#toast')||{}).textContent||'');

// ---- 改成「写对了」 ----
P.click(P.ob('.rate .rate-btn[data-m="1"]'));
await P.wait(260);
P.p('MARK_AFTER_GOOD',ds[0].dataset.mark);
P.p('STATE_TXT_GOOD',(P.ob('.ans-state')||{}).textContent||'');
P.p('BADGE_AFTER_GOOD',(P.ob('#reviewBadge')||{}).textContent||'');
P.p('BADGE_ZERO_GOOD',P.ob('#reviewBadge').dataset.zero);

// ---- 再点一次＝取消 ----
P.click(P.ob('.rate .rate-btn[data-m="1"]'));
await P.wait(260);
P.p('MARK_AFTER_UNDO',ds[0].dataset.mark);
P.p('STORED_EX_AFTER_UNDO',JSON.stringify(JSON.parse(localStorage.getItem(__bench.KEY)||'{}').ex||{}));

// ---- 快捷键 M 标记完成 ----
P.blur();
P.key('m');
await P.wait(220);
P.p('DONE_PRESSED',P.ob('#doneBtn').getAttribute('aria-pressed'));
P.p('DONE_TXT',(P.ob('#doneTxt')||{}).textContent||'');
P.p('DONE_STORED',JSON.stringify(JSON.parse(localStorage.getItem(__bench.KEY)||'{}').done||{}));
P.p('TOAST_DONE',(P.ob('#toast')||{}).textContent||'');

// ---- 作业三态：未做 → 已做 → 卡住 → 取消 ----
var li=P.ob('ol.hw-list > li');
P.p('HW_STATE0',li.dataset.state);
P.p('HW_ID',li.id===li.dataset.hw?'ok':'MISMATCH');
P.p('HW_STUCK_BTN',P.ob('ol.hw-list > li .hw-stuck')?'present':'absent');
var hw=P.ob('ol.hw-list > li .hw-tick input');
if(hw){P.click(hw);await P.wait(220)}
P.p('HW_STATE1',P.ob('ol.hw-list > li').dataset.state);
P.p('HW_TXT',(P.ob('#hwTxt')||{}).textContent||'none');

// 从「已做」翻成「卡住」：这一下必须把它送进错题本，而不是把它取消掉
var sb=P.ob('ol.hw-list > li .hw-stuck');
if(sb){P.click(sb);await P.wait(260)}
P.p('HW_STATE2',P.ob('ol.hw-list > li').dataset.state);
P.p('HW_STUCK_PRESSED',P.ob('ol.hw-list > li .hw-stuck').getAttribute('aria-pressed'));
P.p('HW_STUCK_CHIP',(P.ob('#hwStuck')||{}).textContent||'none');
P.p('HW_TXT_STUCK',(P.ob('#hwTxt')||{}).textContent||'none');
P.p('HW_TOAST',(P.ob('#toast')||{}).textContent||'');
var st=JSON.parse(localStorage.getItem(__bench.KEY)||'{}');
P.p('HW_STORED',JSON.stringify(st.hw||{}));
P.p('HW_REV_DUE_TODAY',(function(){
  var r=st.rev||{},k=Object.keys(r)[0];
  return k&&r[k].due===__bench.dayKey()?'today':'other';
})());
P.p('HW_POOLHW',__bench.revStats().poolHw);
P.p('HW_HWTODO',__bench.revStats().hwTodo);

// 再点一次＝取消：标记和档期要一起清掉，不能留个孤儿档期
var sb2=P.ob('ol.hw-list > li .hw-stuck');
if(sb2){P.click(sb2);await P.wait(260)}
P.p('HW_STATE3',P.ob('ol.hw-list > li').dataset.state);
P.p('HW_REV_AFTER',Object.keys(JSON.parse(localStorage.getItem(__bench.KEY)||'{}').rev||{}).length);
P.p('HW_POOLHW_AFTER',__bench.revStats().poolHw);
P.p('HW_CONSERVE',__bench.revStats().exTotal+'/'+__bench.revStats().hwTotal);

P.p('NO_HSCROLL',document.documentElement.scrollWidth<=document.documentElement.clientWidth+1?'yes':'NO-BAD');
P.p('OVF',P.ovf());
P.p('SMALL',P.small());
P.p('CT_SWEEP',P.contrastSweep());
"""

# 例题默认展开：参考答案一进来就该看得见（#/s1-l1 是唯一带「运行效果」块的一课，
# 顺便验证那个块不算一道题）
EX_OPEN_UI = r"""
await P.ready('.lesson-body');
await P.wait(500);

var ds=P.all('details.answer');
P.p('STEP',(P.ob('.lesson-head h1')||{}).textContent||'');
P.p('CARDS_N',ds.length);
P.p('OPEN_N',ds.filter(function(d){return d.open}).length);
P.p('OUT_N',ds.filter(function(d){return d.classList.contains('out')}).length);
P.p('OUT_LABEL',(P.ob('details.answer.out .ans-label')||{}).textContent||'');
P.p('OUT_OPEN',P.ob('details.answer.out')?P.ob('details.answer.out').open:'none');
P.p('OUT_HAS_RATE',P.all('details.answer.out .rate-btn').length);
P.p('OUT_HAS_ID',P.ob('details.answer.out').id||'');
P.p('ANSWER_LABEL',(P.ob('details.answer:not(.out) .ans-label')||{}).textContent||'');
P.p('RATE_BARS',P.all('details.answer:not(.out) .rate').length);
P.p('EX_GAUGE',(P.ob('#exTxt')||{}).textContent||'none');
P.p('EX_CHIP_N',(function(){
  var cs=P.all('.lesson-head .chip');
  for(var i=0;i<cs.length;i++){
    var m=/例题\s*(\d+)/.exec(cs[i].textContent);
    if(m) return m[1];
  }
  return '';
})());
P.p('EXPAND_BTN',(P.ob('#expandAll')||{}).textContent||'');
P.p('CODE_H',(function(){
  var b=P.ob('details.answer:not(.out) .hl');
  return b?Math.round(b.getBoundingClientRect().height):-1;
})());
P.p('ANS_TXT_HAS_PRINT',/print/.test(P.ob('details.answer:not(.out) .hl').textContent)?'yes':'NO-BAD');
P.p('OUT_TXT_HAS_NAME',/姓名/.test(P.ob('details.answer.out .hl').textContent)?'yes':'NO-BAD');

// 收起／展开全部：按钮文案与状态都要跟着走
P.click(P.ob('#expandAll'));
await P.wait(280);
P.p('BTN_AFTER_COLLAPSE',(P.ob('#expandAll')||{}).textContent||'');
P.p('OPEN_N_COLLAPSED',P.all('details.answer').filter(function(d){return d.open}).length);
P.click(P.ob('#expandAll'));
await P.wait(280);
P.p('BTN_AFTER_REOPEN',(P.ob('#expandAll')||{}).textContent||'');
P.p('OPEN_N_REOPENED',P.all('details.answer').filter(function(d){return d.open}).length);

P.p('NO_HSCROLL',document.documentElement.scrollWidth<=document.documentElement.clientWidth+1?'yes':'NO-BAD');
P.p('OVF',P.ovf());
P.p('SMALL',P.small());
P.p('CT_SWEEP',P.contrastSweep());
"""

REVIEW_UI = r"""
await P.ready('.tabs');
await P.wait(400);

P.p('TABS',P.all('.tab').map(function(t){return t.dataset.tab}).join(' '));
P.p('TAB_COUNTS',P.all('.tab i').map(function(i){return i.textContent}).join('/'));
P.p('TAB_SELECTED',P.all('.tab').filter(function(t){return t.getAttribute('aria-selected')==='true'}).map(function(t){return t.dataset.tab}).join(' '));
P.p('PANEL_ROLE',P.ob('#rvPanel')?P.ob('#rvPanel').getAttribute('role'):'none');
P.p('CARDS_DEFAULT',P.all('.rv-card').length);

// 空错题本时不该摆出「开始复习」按钮
P.p('START_BTN_EMPTY',P.ob('#rvStart')?'present':'absent');

// 切到「该复习」——此时一条都没有
P.click(P.ob('.tab[data-tab="due"]'));
await P.wait(300);
P.p('DUE_EMPTY',!!P.ob('.empty'));
P.p('DUE_EMPTY_TXT',(P.ob('.empty b')||{}).textContent||'');

// 切到「未评价」
P.click(P.ob('.tab[data-tab="fresh"]'));
await P.wait(300);
P.p('FRESH_N',P.all('.rv-card').length);
P.p('FRESH_FIRST',(P.ob('.rv-card .rv-txt b')||{}).textContent||'');
P.p('FRESH_FIRST_LESSON',(P.ob('.rv-card .rv-txt .rv-src')||{}).textContent||'');
P.p('FRESH_NO_DUE_TAG',P.ob('.rv-card .rv-due')?'leaked':'clean');
P.p('JUMP_HREF',(P.ob('.rv-card .rv-go')||{}).getAttribute('href')||'');

// 列表里直接标记：新错题当天就到期，所以会立刻出现在「该复习」
P.click(P.ob('.rv-card .rate-btn[data-m="-1"]'));
await P.wait(320);
P.p('DUE_COUNT_AFTER',P.all('.tab[data-tab="due"] i').map(function(i){return i.textContent})[0]);
P.p('BADGE_AFTER',(P.ob('#reviewBadge')||{}).textContent||'');
var st=JSON.parse(localStorage.getItem(__bench.KEY)||'{}');
P.p('STORED_EX',JSON.stringify(st.ex||{}));
P.p('STORED_REV_KEYS',Object.keys(st.rev||{}).length);
P.p('STORED_REV_DUE',(st.rev||{})[Object.keys(st.rev||{})[0]].due===__bench.dayKey()?'today':'other');

// 回「该复习」应该正好一条，并且显示今天到期
P.click(P.ob('.tab[data-tab="due"]'));
await P.wait(300);
P.p('DUE_CARDS',P.all('.rv-card').length);
P.p('DUE_CARD_MARK',P.ob('.rv-card').dataset.mark);
P.p('DUE_TAG_NOW',(P.ob('.rv-due[data-now="1"]')||{}).textContent||'');
P.p('START_BTN_NOW',((P.ob('#rvStart')||{}).textContent||'').replace(/\s+/g,' ').trim());

// 「去复习」跳转 + 定位高亮。
// 答案现在默认展开，所以先把目标那道题手动收起来，再验证跳转确实会重新展开它
// ——否则这个断言等于白测。
var go=P.ob('.rv-card .rv-go');
var target=go.dataset.jump;
location.hash=go.getAttribute('href');
await P.wait(800);
var pre=document.getElementById(target);
P.p('TARGET_PRE',pre?'found':'missing');
if(pre){ pre.open=false; }
P.p('PRE_COLLAPSED',pre?String(!pre.open):'no-el');
location.hash='#/review';
await P.wait(800);
P.click(P.ob('.rv-card .rv-go'));
await P.wait(600);
var jx=document.getElementById(target);
P.p('HASH',location.hash);
P.p('JUMPED_OPEN',!!jx&&jx.open);
P.p('JUMPED_FLASH',!!jx&&jx.classList.contains('is-flash'));
P.p('JUMPED_ID',jx?jx.id:'none');
P.p('JUMPED_MARK',jx?jx.dataset.mark:'none');
P.p('JUMP_VISIBLE',(jx&&jx.classList.contains('is-flash'))?'yes':'NO-BAD');
P.p('JUMPED_EX_ATTR',jx?jx.dataset.ex:'none');
P.p('RATE_IN_JUMPED',jx?jx.querySelectorAll('.rate-btn').length:-1);
P.p('ANS_STATE_TXT',jx?((jx.querySelector('.ans-state')||{}).textContent||''):'none');

P.p('NO_HSCROLL',document.documentElement.scrollWidth<=document.documentElement.clientWidth+1?'yes':'NO-BAD');
P.p('OVF',P.ovf());
P.p('SMALL',P.small());
P.p('CT_SWEEP',P.contrastSweep());
"""

# 间隔复习：从分栏 → 开一轮 → 答错回档 / 答对升档 / 走完全程毕业
SPACED_UI = r"""
await P.ready('.tabs');
await P.wait(500);

// ---- 分栏与徽章口径 ----
P.p('TABS',P.all('.tab').map(function(t){return t.dataset.tab}).join(' '));
P.p('TAB_COUNTS',P.all('.tab i').map(function(i){return i.textContent}).join('/'));
P.p('BADGE',(P.ob('#reviewBadge')||{}).textContent||'');
P.p('DUE_CARDS',P.all('.rv-card').length);
// 欠得最久的排在最前
P.p('DUE_FIRST_ID',(P.ob('.rv-card .rv-go')||{}).dataset.jump||'');
P.p('OVERDUE_TAG',(P.ob('.rv-due[data-late="1"]')||{}).textContent||'');
P.p('NOW_TAGS',P.all('.rv-due[data-now="1"]').length);
// 阶梯五档：l 依次 1/2/1/4 → 0/2/1/0/1
P.p('LADDER',P.all('.rv-lad li b').map(function(b){return b.textContent}).join('/'));
P.p('LADDER_LABELS',P.all('.rv-lad li span').map(function(s){return s.textContent}).join('/'));

// ---- 未到期的题不该漏进「该复习」 ----
P.click(P.ob('.tab[data-tab="later"]'));
await P.wait(300);
P.p('LATER_N',P.all('.rv-card').length);
P.p('LATER_NO_OVERDUE',P.all('.rv-card .rv-due').filter(function(e){
  return e.dataset.now||e.dataset.late}).length===0?'yes':'NO-BAD');

P.click(P.ob('.tab[data-tab="due"]'));
await P.wait(300);
P.p('START_TXT',((P.ob('#rvStart')||{}).textContent||'').replace(/\s+/g,' ').trim());
P.p('BAR_IDLE',P.ob('#rvBar').dataset.show);

// ---- 开一轮：应跳到欠得最久的那道，并自动展开高亮 ----
P.click(P.ob('#rvStart'));
await P.wait(1000);
P.p('BAR_ON',P.ob('#rvBar').dataset.show);
P.p('BAR_N',(P.ob('#rvBarN')||{}).textContent||'');
P.p('BAR_T',(P.ob('#rvBarT')||{}).textContent||'');
P.p('S1_HASH',location.hash);
P.p('S1_IDS',JSON.stringify(__bench.getSession().ids));
var fx=document.querySelector('details.answer.is-flash');
P.p('S1_FLASH_ID',fx?fx.id:'none');
P.p('S1_OPEN',!!fx&&fx.open);

// ---- 第一道答错：退回第一档，明天再来 ----
P.click(fx.querySelector('.rate-btn[data-m="-1"]'));
await P.wait(900);
var st=__bench.getState();
P.p('R1_REV',JSON.stringify(st.rev['ex-s1-l1-1']));
P.p('R1_MARK',String(st.ex['ex-s1-l1-1']));
P.p('R1_MSG',(P.ob('#toast')||{}).textContent||'');
P.p('R1_DONE',String(__bench.getSession().done));
P.p('R1_HASH',location.hash);

// ---- 第二道答对：升一档，同一课内推进 ----
var fx2=document.querySelector('details.answer.is-flash');
P.p('S2_FLASH_ID',fx2?fx2.id:'none');
P.click(fx2.querySelector('.rate-btn[data-m="1"]'));
await P.wait(900);
st=__bench.getState();
P.p('R2_REV',JSON.stringify(st.rev['ex-s1-l1-2']));
P.p('R2_MSG',(P.ob('#toast')||{}).textContent||'');
P.p('R2_HASH',location.hash);

// ---- 第三道过最后一关：毕业，转已掌握 ----
var fx3=document.querySelector('details.answer.is-flash');
P.p('S3_FLASH_ID',fx3?fx3.id:'none');
P.click(fx3.querySelector('.rate-btn[data-m="1"]'));
await P.wait(1100);
st=__bench.getState();
P.p('R3_HAS_REV',Object.prototype.hasOwnProperty.call(st.rev,'ex-s1-l3-0')?'yes':'no');
P.p('R3_MARK',String(st.ex['ex-s1-l3-0']));
P.p('R3_MSG',(P.ob('#toast')||{}).textContent||'');
P.p('BAR_END',P.ob('#rvBar').dataset.show);
P.p('SESSION_END',__bench.getSession()?'still':'cleared');

// ---- 收尾核对：处理过的题当天不会再到期 ----
location.hash='#/review';
await P.wait(700);
P.p('BADGE_AFTER',(P.ob('#reviewBadge')||{}).textContent||'');
P.p('TAB_AFTER',P.all('.tab i').map(function(i){return i.textContent}).join('/'));
P.p('STILL_DUE_SAME_DAY',(function(){
  var r=__bench.getState().rev, t=__bench.dayKey();
  return Object.keys(r).filter(function(k){return r[k].due<=t}).length;
})());
P.p('NO_HSCROLL',document.documentElement.scrollWidth<=document.documentElement.clientWidth+1?'yes':'NO-BAD');
P.p('OVF',P.ovf());
P.p('SMALL',P.small());
P.p('CT_SWEEP',P.contrastSweep());
"""

RECORDS_UI = r"""
await P.ready('.hm');
await P.wait(500);

P.p('REC_CARDS',P.all('.rec-grid')[0].children.length);
P.p('HM_CELLS',P.all('.hm-c').length);
P.p('HM_ROWS',P.cs(P.ob('.hm'),'gridTemplateRows').split(' ').length);
P.p('HM_TODAY',!!P.ob('.hm-c[data-today="1"]'));
P.p('HM_TODAY_L',P.ob('.hm-c[data-today="1"]').dataset.l);
P.p('STAT_TODAY',(P.ob('.rec-grid .rec-card b')||{}).textContent||'');
P.p('STREAK_BEFORE',P.all('.rec-grid .rec-card b')[3].textContent);
P.p('PROG_CARDS',P.all('.rec-grid')[1].children.length);
P.p('PROG_TXT',(function(){
  var pc=Array.prototype.slice.call(P.all('.rec-grid')[1].children);
  return pc.length+'|'+pc.map(function(c){return c.textContent.replace(/\s+/g,' ').trim()}).join(' / ');
})());

// ---- 真实计时路径：心跳要求页面可见，无头下先把它掰成 visible ----
P.p('VIS',document.visibilityState);
try{
  Object.defineProperty(document,'visibilityState',
    {get:function(){return 'visible'},configurable:true});
}catch(e){ P.p('VIS_PATCH_ERR',String(e).slice(0,120)); }
document.dispatchEvent(new Event('mousemove'));
await P.wait(12000);
P.p('VIS_AFTER',document.visibilityState);
P.p('TIME_AFTER_TICK',JSON.stringify(__bench.getState().time));
P.p('TICK_COUNTED',Object.keys(__bench.getState().time).length>0);

// ---- 用调试钩子补写历史，验证热力等级与连续天数 ----
var st=__bench.getState();
st.time[__bench.dayKey()]=0;
__bench.addTime(3600);
var d1=new Date();d1.setDate(d1.getDate()-1);
st.time[__bench.dayKey(d1)]=900;
var d2=new Date();d2.setDate(d2.getDate()-2);
st.time[__bench.dayKey(d2)]=1200;
__bench.refresh();
P.p('HM_TODAY_L_AFTER',P.ob('.hm-c[data-today="1"]').dataset.l);
P.p('STAT_TODAY_AFTER',(P.ob('.rec-grid .rec-card b')||{}).textContent||'');
P.p('STAT_WEEK',P.all('.rec-grid .rec-card b')[1].textContent);
P.p('STREAK_AFTER',P.all('.rec-grid .rec-card b')[3].textContent);
P.p('HM_FILLED',P.all('.hm-c').filter(function(c){return c.dataset.l!=='0'}).length);
P.p('HM_TITLE_SAMPLE',P.ob('.hm-c').getAttribute('title'));
P.p('FMT',__bench.fmtDur(3600)+'|'+__bench.fmtDur(900)+'|'+__bench.fmtDur(59));

// ---- 复习阶梯小结：没有错题时不该占地方，有错题才出现 ----
P.p('REC_NOTE_BEFORE',P.ob('.rec-note')?'present':'absent');
__bench.rateEx('ex-s1-l1-1',-1,true);
__bench.render();
await P.wait(400);
P.p('REC_NOTE_AFTER',P.ob('.rec-note')?'present':'absent');
P.p('REC_NOTE_STEPS',P.all('.rec-note span').map(function(s){
  return s.textContent.replace(/\s+/g,'')}).join('/'));
P.p('REC_DUE_CARD',P.all('.rec-grid')[1].children[1].textContent.replace(/\s+/g,' ').trim());

// ---- 导出 ----
// 不能在无头里真的触发下载：Chrome 会挂。拦下 a.click()，
// 直接 fetch 那个 blob 校验导出内容——比只看「点过了」更有信息量。
var origClick=HTMLAnchorElement.prototype.click, cap=null;
HTMLAnchorElement.prototype.click=function(){ cap={href:this.href,download:this.download}; };
P.click(P.ob('#expBtn'));
await P.wait(400);
HTMLAnchorElement.prototype.click=origClick;
P.p('EXPORT_CLICKED',!!cap);
P.p('EXPORT_NAME',cap?cap.download:'none');
P.p('EXPORT_BLOB',cap?cap.href.slice(0,5):'none');
P.p('EXPORT_TOAST',(P.ob('#toast')||{}).textContent||'');
if(cap&&cap.href.indexOf('blob:')===0){
  try{
    var resp=await fetch(cap.href), txt=await resp.text(), obj=JSON.parse(txt);
    P.p('EXP_APP',obj.app);
    P.p('EXP_VER',obj.version);
    P.p('EXP_STATE_KEYS',Object.keys(obj.state||{}).sort().join(','));
    P.p('EXP_TIME',JSON.stringify((obj.state||{}).time||{}));
    P.p('EXP_REV',JSON.stringify((obj.state||{}).rev||{}));
    P.p('EXP_BYTES',txt.length);
  }catch(e){ P.p('EXP_FETCH_ERR',String(e).slice(0,200)); }
}

// ---- 导入：合并语义 ----
var payload=JSON.stringify({
  app:'python-learning-path',
  version:2,
  state:{
    done:{'s1-l1':1},
    hw:{'s1-l1:0':1},
    miles:{'0':1},
    ex:{'ex-s1-l1-0':1},
    time:{'2020-01-01':1200}
  }
});
function feed(text,name){
  var f=new File([text],name||'backup.json',{type:'application/json'});
  var dt=new DataTransfer();dt.items.add(f);
  var inp=P.ob('#impFile');
  inp.files=dt.files;
  inp.dispatchEvent(new Event('change',{bubbles:true}));
}
// FileReader 是真实异步 I/O，虚拟时钟推不动它——直接等我们要观察的结果出现
function toastTxt(){return (P.ob('#toast')||{}).textContent||''}

feed(payload);
await P.until(function(){return __bench.getState().done['s1-l1']===1});
var s2=__bench.getState();
P.p('IMPORT_DONE',s2.done['s1-l1']||0);
P.p('IMPORT_HW',s2.hw['s1-l1:0']||0);
P.p('IMPORT_MILES',s2.miles['0']||0);
P.p('IMPORT_EX',s2.ex['ex-s1-l1-0']||0);
P.p('IMPORT_TIME',s2.time['2020-01-01']||0);
P.p('IMPORT_TOAST',toastTxt());
P.p('IMPORT_BADGE',(P.ob('#reviewBadge')||{}).textContent||'');
P.p('IMPORT_RERENDERED',!!P.ob('#recStats'));

// 再导入一次同样内容：不应该重复累加
feed(payload,'again.json');
await P.until(function(){return /没有新内容/.test(toastTxt())});
P.p('IMPORT_TWICE_TIME',__bench.getState().time['2020-01-01']||0);
P.p('IMPORT_TWICE_TOAST',toastTxt());
P.p('IMPORT_TWICE_DONE',Object.keys(__bench.getState().done).length);

// 坏文件不该崩，也不该改数据
var before=JSON.stringify(__bench.getState().done);
feed('这不是 JSON','bad.json');
await P.until(function(){return /导入失败/.test(toastTxt())});
P.p('IMPORT_BAD_TOAST',toastTxt());
P.p('IMPORT_BAD_SAFE',JSON.stringify(__bench.getState().done)===before?'yes':'NO-BAD');

// ---- 清空：两段式确认 ----
var clr=P.ob('#clrBtn');
P.click(clr);
await P.wait(250);
P.p('CLR_ARMED',clr.dataset.arm);
P.p('CLR_ARMED_TXT',clr.textContent);
P.p('CLR_STATE_INTACT',Object.keys(__bench.getState().done).length);
P.click(P.ob('#clrBtn'));
await P.wait(400);
P.p('CLR_DONE_STATE',JSON.stringify(__bench.getState().done));
P.p('CLR_TOAST',(P.ob('#toast')||{}).textContent||'');
P.p('CLR_BADGE_AFTER',(P.ob('#reviewBadge')||{}).textContent||'');

P.p('NO_HSCROLL',document.documentElement.scrollWidth<=document.documentElement.clientWidth+1?'yes':'NO-BAD');
P.p('OVF',P.ovf());
P.p('SMALL',P.small());
P.p('HM_SCROLLS',P.ob('.hm-scroll').scrollWidth>P.ob('.hm-scroll').clientWidth?'yes':'no');
P.p('CT_SWEEP',P.contrastSweep());
"""

NARROW_UI = r"""
await P.ready('.hero');
await P.wait(500);

P.p('VW',document.documentElement.clientWidth);
P.p('GRID_COLS',P.cs(P.ob('.app'),'gridTemplateColumns'));
P.p('GRID_ROWS',P.cs(P.ob('.app'),'gridTemplateRows').split(' ').length);
P.p('SIDEBAR_POS',P.cs(P.ob('#sidebar'),'position'));
P.p('MAIN_GEO',P.geo('.main'));
P.p('TOPBAR_GEO',P.geo('.topbar'));
P.p('STAGE_COLS',P.cs(P.ob('.stage-grid'),'gridTemplateColumns').split(' ').length);
P.p('NO_HSCROLL_HOME',document.documentElement.scrollWidth<=document.documentElement.clientWidth+1?'yes':'NO-BAD');
P.p('OVF_HOME',P.ovf());
P.p('SMALL_HOME',P.small());
P.p('MENU_BTN',P.cs(P.ob('#menuBtn'),'display'));

// ---- 抽屉 ----
P.click(P.ob('#menuBtn'));
await P.wait(300);
P.p('DRAWER_OPEN',P.ob('#sidebar').dataset.open);
P.p('SCRIM_OPEN',P.ob('#scrim').dataset.open);
P.p('DRAWER_LEFT',Math.round(P.ob('#sidebar').getBoundingClientRect().left));
P.p('BODY_LOCKED',document.body.style.overflow);
P.click(P.ob('#scrim'));
await P.wait(300);
P.p('DRAWER_CLOSED',P.ob('#sidebar').dataset.open);

// ---- 错题本页 ----
location.hash='#/review';
await P.wait(700);
P.p('RV_TABS_W',Math.round(P.ob('.tabs').getBoundingClientRect().width));
P.p('RV_CONTENT_W',Math.round(P.ob('#contentRoot').getBoundingClientRect().width));
P.p('RV_CARD_DIR',P.cs(P.ob('.rv-card'),'flexDirection'));
P.p('RV_ACT_WRAP',P.cs(P.ob('.rv-act'),'flexWrap'));
P.p('NO_HSCROLL_RV',document.documentElement.scrollWidth<=document.documentElement.clientWidth+1?'yes':'NO-BAD');
P.p('OVF_RV',P.ovf());
P.p('SMALL_RV',P.small());

// ---- 学习记录页 ----
location.hash='#/records';
await P.wait(700);
P.p('REC_COLS',P.cs(P.ob('.rec-grid'),'gridTemplateColumns').split(' ').length);
P.p('HM_SCROLLS',P.ob('.hm-scroll').scrollWidth>P.ob('.hm-scroll').clientWidth?'yes':'no');
P.p('HM_OVERFLOW_X',P.cs(P.ob('.hm-scroll'),'overflowX'));
P.p('NO_HSCROLL_REC',document.documentElement.scrollWidth<=document.documentElement.clientWidth+1?'yes':'NO-BAD');
P.p('OVF_REC',P.ovf());
P.p('SMALL_REC',P.small());
"""

# 窄屏场景在最后额外压一次课程页
NARROW_TAIL = r"""
location.hash='#/s3-l17';
await P.wait(800);
P.p('RATE_W',Math.round(P.ob('.rate-btn').getBoundingClientRect().width));
P.p('RATE_H',Math.round(P.ob('.rate-btn').getBoundingClientRect().height));
P.p('RATE_Q_BLOCK',P.cs(P.ob('.rate-q'),'width'));
P.p('HINT_HIDDEN',P.cs(P.ob('.ans-hint'),'display'));
P.p('NO_HSCROLL_LESSON',document.documentElement.scrollWidth<=document.documentElement.clientWidth+1?'yes':'NO-BAD');
P.p('OVF_LESSON',P.ovf());
P.p('SMALL_LESSON',P.small());
P.p('CT_SWEEP',P.contrastSweep());
"""

EX_STALE_UI = r"""
await P.ready('.tabs');
await P.wait(500);

// 侧栏徽章与错题本列表必须报同一个数
P.p('BADGE',(P.ob('#reviewBadge')||{}).textContent||'');
P.p('BADGE_ZERO',(P.ob('#reviewBadge')||{}).dataset.zero);
P.p('TAB_DUE_CNT',P.all('.tab')[0].querySelector('i').textContent);
P.p('TAB_COUNTS',P.all('.tab i').map(function(i){return i.textContent}).join('/'));
P.p('DUE_CARDS',P.all('.rv-card').length);
P.p('DUE_TAB_ARIA',P.all('.tab')[0].getAttribute('aria-selected'));

// v2 老数据升上来：没有档期记录的错题要立刻到期，不能被新功能吞掉
var st=__bench.getState();
P.p('KEY_UPGRADED',localStorage.getItem(__bench.KEY)?'yes':'no');
P.p('MIGRATED_DUE',['ex-s1-l1-1','ex-s1-l3-1'].every(function(k){
  var r=st.rev[k];
  return !!r&&r.due===__bench.dayKey()&&r.l===0&&r.n===0;
})?'yes':'NO-BAD');

// 首页英雄区那块统计也要一致
location.hash='#/';
await P.wait(700);
P.p('HERO_REVIEW',(function(){
  var els=P.all('.stat,.hero-stat');
  for(var i=0;i<els.length;i++){
    if(/错题|该复习/.test(els[i].textContent)) return els[i].textContent.replace(/\s+/g,' ').trim();
  }
  return '';
})());
P.p('NO_HSCROLL',document.documentElement.scrollWidth<=document.documentElement.clientWidth+1?'yes':'NO-BAD');
P.p('OVF',P.ovf());
P.p('SMALL',P.small());
P.p('CT_SWEEP',P.contrastSweep());
"""

# 作业入复习闭环：标了「卡住」的作业要和例题一样进错题本、能跳回原位高亮、
# 按同一套档期复习，而且评分是「判定」不是「把标记点掉」。
HW_STUCK_UI = r"""
await P.ready('.tabs');
await P.wait(450);

P.p('TAB_COUNTS',P.all('.tab i').map(function(i){return i.textContent}).join('/'));

// 两类欠债混排在同一个队列里，各带各的来源徽章
P.p('KINDS',P.all('.rv-card[data-kind]').map(function(c){return c.dataset.kind}).sort().join(' '));
P.p('BADGES',P.all('.rv-card .rv-kind').map(function(k){return k.textContent}).sort().join(' '));
P.p('HW_LABELS',P.all('.rv-card[data-kind="hw"] .rate-btn').map(function(b){return b.textContent.trim()}).join('|'));
P.p('EX_LABELS',P.all('.rv-card[data-kind="ex"] .rate-btn').map(function(b){return b.textContent.trim()}).join('|'));
P.p('HW_GO_TXT',(P.ob('.rv-card[data-kind="hw"] .rv-go')||{}).textContent.replace(/\s+/g,' ').trim());
P.p('HW_LATE',P.all('.rv-card[data-kind="hw"] .rv-due[data-late="1"]').length);

// 两条守恒式各自成立：例题 45 那道不变，作业另立一道
var s=__bench.revStats();
P.p('EX_CONSERVE',s.poolEx+'+'+s.fresh+'+'+s.doneEx+'='+s.exTotal);
P.p('HW_CONSERVE',s.poolHw+'+'+s.hwDone+'+'+s.hwTodo+'='+s.hwTotal);
P.p('POOL',s.poolEx+'/'+s.poolHw);

// 「去重做」把人送回那一课，并高亮那条作业
var go=P.ob('.rv-card[data-kind="hw"] .rv-go');
var target=go.dataset.jump;
P.click(go);
await P.wait(900);
var el=document.getElementById(target);
P.p('HASH',location.hash);
P.p('TARGET_TAG',el?el.tagName:'none');
P.p('TARGET_FLASH',!!el&&el.classList.contains('is-flash'));
P.p('TARGET_STATE',el?el.dataset.state:'none');
P.p('TARGET_STUCK_PRESSED',el?el.querySelector('.hw-stuck').getAttribute('aria-pressed'):'none');
P.p('TARGET_TICK',el?String(el.querySelector('.hw-tick input').checked):'none');

// 判定语义：这条已经连对 4 次，再答对一次就该毕业。
// 关键——它记的是「做出来了」，不是把标记点掉，所以 hw 里留下的必须是 1 而不是消失。
location.hash='#/review';
await P.wait(700);
var rb=P.ob('.rv-card[data-kind="hw"] .rate-btn[data-m="1"]');
if(rb){P.click(rb);await P.wait(450)}
P.p('TOAST',(P.ob('#toast')||{}).textContent||'');
P.p('MARK_AFTER',__bench.markGet(target));
P.p('HW_DONE',__bench.revStats().hwDone);
P.p('HW_POOL_AFTER',__bench.revStats().poolHw);
P.p('DUE_AFTER',(P.ob('.tab[data-tab="due"] i')||{}).textContent||'none');
P.p('HW_GONE',P.all('.rv-card[data-kind="hw"]').length);
P.p('HW_CONSERVE_AFTER',(function(){
  var t=__bench.revStats();return t.poolHw+'+'+t.hwDone+'+'+t.hwTodo+'='+t.hwTotal;
})());

P.p('NO_HSCROLL',document.documentElement.scrollWidth<=document.documentElement.clientWidth+1?'yes':'NO-BAD');
P.p('OVF',P.ovf());
P.p('SMALL',P.small());
P.p('CT_SWEEP',P.contrastSweep());
"""

# 抽题自测：索引口径 → 分层抽样 → 遮答案 → 揭示 → 判定 → 成绩单
# 种子里 s1 的 16 道例题全部标成「已掌握」，所以无论抽到哪 5 道都必然是
# T0（最久没被检验的那一层）——「答错就退回错题本」的断言才不依赖随机顺序。
QUIZ_UI = r"""
await P.ready('.qz-setup');
await P.wait(400);

// ---- 抽题索引的口径必须和错题本一字不差，否则自测判的错落不到错题本上 ----
P.p('QUIZ_N',__bench.quizIndex().length);
P.p('EX_N',__bench.exIndex().length);
P.p('IDS_MATCH',(function(){
  var a=__bench.quizIndex().map(function(x){return x.id}).sort().join(','),
      b=__bench.exIndex().map(function(x){return x.id}).sort().join(',');
  return a===b?'yes':'MISMATCH';
})());
P.p('Q_EMPTY',__bench.quizIndex().filter(function(x){return !x.q}).length);
P.p('A_EMPTY',__bench.quizIndex().filter(function(x){return !x.a}).length);
// 题面里绝不能印着答案（一标题多答案的那两道最容易犯）
P.p('LEAK',__bench.quizIndex().filter(function(x){return x.q.indexOf(x.a)>=0}).length);
P.p('MULTI_TITLE',__bench.quizIndex().filter(function(x){return /（\d\/\d）$/.test(x.title)}).length);

// ---- 分层：会了 → 0，没表态 → 1，错题本里 → 2 ----
P.p('TIER_MASTERED',__bench.quizTier('ex-s1-l1-1'));
P.p('TIER_FRESH',__bench.quizTier('ex-s3-l17-0'));
P.p('TIER_POOL',__bench.quizTier('ex-s2-l9-0'));

// ---- 设置页 ----
P.p('COLD_CHIP',(function(){
  var c=P.all('.chip').filter(function(e){return e.textContent.indexOf('没复核')>=0});
  return c.length?c[0].querySelector('b').textContent:'none';
})());
P.p('SEG_SIZES',P.all('[data-qz-size]').map(function(b){return b.textContent.trim()}).join('/'));
P.p('SEG_SRC',P.all('[data-qz-src]').map(function(b){return b.textContent.trim()}).join('/'));
P.p('SCOPE_OPTS',P.all('#qzScope option').length);
P.p('OVF',P.ovf());
P.p('SMALL',P.small());
P.p('CT_SWEEP_SETUP',P.contrastSweep());

// ---- 组卷：范围 s1 + 只例题 → 全是 T0 的例题 ----
__bench.setQzSetup({scope:'s1',size:5,source:'ex'});
__bench.startQuiz();
await P.wait(600);
P.p('HASH',location.hash);
P.p('QZ_N',__bench.getQuiz().rows.length);
P.p('ROW_TIERS',__bench.getQuiz().rows.map(function(r){return __bench.quizTier(r.id)}).join(''));
P.p('ROW_KINDS',__bench.getQuiz().rows.map(function(r){return r.kind}).join(','));
P.p('ROW_HAS_A',__bench.getQuiz().rows.filter(function(r){return !!r.a}).length);

// ---- 出题时答案必须是遮住的 ----
P.p('ANS_HIDDEN',P.ob('#qzAns').hidden?'yes':'NO-BAD');
P.p('ANS_DISPLAY',P.cs(P.ob('#qzAns'),'display'));
P.p('RATE_HIDDEN',P.ob('#qzRate').hidden?'yes':'NO-BAD');
P.p('RATE_DISPLAY',P.cs(P.ob('#qzRate'),'display'));
P.p('ACT_SHOWN',P.ob('#qzAct').hidden?'NO-BAD':'yes');
P.p('REVEAL_TXT',P.ob('#qzReveal').textContent.replace(/\s+/g,' ').trim());
P.p('COUNT_TXT',P.ob('.qz-count').textContent.replace(/\s+/g,' ').trim());
P.p('WARN_BADGE',(P.ob('.qz-badge')||{}).textContent||'none');
P.p('Q_LEN',P.ob('.qz-body').textContent.trim().length);
P.p('Q_CODE_BLOCKS',P.all('.qz-body .hl').length);
// 题面只有标题的题有多少道；卡片上的提示必须与当前这道题的真实情况一致
P.p('BARE_N',__bench.quizIndex().filter(function(x){return x.bare}).length);
P.p('BARE_HINT_MATCH',(function(){
  var r=__bench.getQuiz().rows[__bench.getQuiz().idx];
  return (!!r.bare)===!!P.ob('.qz-bare')?'yes':'MISMATCH';
})());
P.p('FOOT_HREF',(P.ob('.qz-foot .rv-go')||{}).getAttribute('href')||'');
P.p('FOOT_ITEM_OK',(function(){
  var r=__bench.getQuiz().rows[__bench.getQuiz().idx];
  return P.ob('.qz-foot .rv-go').getAttribute('href')==='#/'+r.itemId?'yes':'NO-BAD';
})());

// ---- 揭示答案 ----
var id1=__bench.getQuiz().rows[0].id;
P.p('ID1',id1);
P.click(P.ob('#qzReveal'));
await P.wait(350);
P.p('ANS_AFTER',P.ob('#qzAns').hidden?'NO-BAD':'visible');
P.p('ANS_DISPLAY_AFTER',P.cs(P.ob('#qzAns'),'display'));
P.p('RATE_AFTER',P.ob('#qzRate').hidden?'NO-BAD':'visible');
P.p('ACT_AFTER',P.ob('#qzAct').hidden?'hidden':'NO-BAD');
P.p('ANS_CODE',P.all('#qzAns .hl').length);
P.p('ANS_TOUCH',P.all('#qzRate .btn').map(function(b){var r=b.getBoundingClientRect();
  return (r.width>=44&&r.height>=44)?'ok':'SMALL-'+Math.round(r.width)+'x'+Math.round(r.height)}).join(','));
P.p('OVF_Q',P.ovf());
P.p('SMALL_Q',P.small());
P.p('CT_SWEEP',P.contrastSweep());

// ---- 答错一道「已掌握」的题：必须退回错题本，今天就重做 ----
P.click(P.ob('[data-qz-rate="-1"]'));
await P.wait(1200);
var st=__bench.getState();
P.p('W_MARK',String(st.ex[id1]));
P.p('W_REV',JSON.stringify(st.rev[id1]));
P.p('W_MSG',(P.ob('#toast')||{}).textContent||'');
P.p('W_IDX',String(__bench.getQuiz().idx));
P.p('W_NEXT_HIDDEN',P.ob('#qzAns')?(P.ob('#qzAns').hidden?'yes':'NO-BAD'):'na');
P.p('W_DUE_NOW',(st.rev[id1]&&st.rev[id1].due===__bench.dayKey())?'yes':'NO-BAD');

// ---- 答对一道：复核通过，仍在已掌握 ----
var id2=__bench.getQuiz().rows[1].id;
P.p('ID2',id2);
P.click(P.ob('#qzReveal'));
await P.wait(300);
P.click(P.ob('[data-qz-rate="1"]'));
await P.wait(1200);
st=__bench.getState();
P.p('R2_MARK',String(st.ex[id2]));
P.p('R2_MSG',(P.ob('#toast')||{}).textContent||'');
P.p('R2_IDX',String(__bench.getQuiz().idx));

// ---- 跳过：状态一动不能动 ----
var id3=__bench.getQuiz().rows[2].id;
P.p('ID3',id3);
P.click(P.ob('#qzSkip'));
await P.wait(500);
P.p('SKIP_MARK',String(__bench.getState().ex[id3]));
P.p('SKIP_IDX',String(__bench.getQuiz().idx));

// ---- 结束 → 成绩单 ----
P.click(P.ob('#qzQuit'));
await P.wait(600);
P.p('RES_SHOWN',P.ob('.qz-score')?'yes':'NO-BAD');
P.p('RES_SCORE',P.ob('.qz-score-main').textContent.replace(/\s+/g,'').trim());
P.p('RES_ROWS',P.all('.qz-row').length);
P.p('RES_MARKS',P.all('.qz-mark').map(function(m){return m.dataset.r}).join(','));
P.p('RES_SIDE',P.ob('.qz-score-side').textContent.replace(/\s+/g,' ').trim());
P.p('OVF_RES',P.ovf());
P.p('SMALL_RES',P.small());
P.p('CT_SWEEP_RES',P.contrastSweep());

// ---- 再来一组：重新抽，回到第一题 ----
P.click(P.ob('#qzAgain'));
await P.wait(700);
P.p('AGAIN_N',String(__bench.getQuiz().rows.length));
P.p('AGAIN_IDX',String(__bench.getQuiz().idx));
P.p('AGAIN_CARD',P.ob('.qz-card')?'yes':'NO-BAD');

// ---- 收尾：结果必须落在错题本/已掌握的正确栏位里 ----
location.hash='#/review';
await P.wait(800);
P.p('DUE_HAS_DEMOTED',__bench.revStats().rows.due.filter(function(x){return x.id===id1}).length);
P.p('DONE_HAS_OK',__bench.revStats().rows.done.filter(function(x){return x.id===id2}).length);
P.p('DONE_HAS_SKIP',__bench.revStats().rows.done.filter(function(x){return x.id===id3}).length);
P.p('POOL_TOTAL',__bench.revStats().pool);
P.p('NO_HSCROLL',document.documentElement.scrollWidth<=document.documentElement.clientWidth+1?'yes':'NO-BAD');
"""

TODAY_UI = r"""
await P.ready('.today');
await P.wait(450);

// ---- 四张卡：数量、顺序、去处 ----
P.p('PLAN_CARDS',P.all('.today-card').length);
P.p('PLAN_KEYS',P.all('.today-card').map(function(a){return a.dataset.k}).join(','));
P.p('PLAN_HREFS',P.all('.today-card').map(function(a){return a.getAttribute('href')}).join(' '));
P.p('PLAN_DATE',P.ob('.today-date').textContent.trim());
P.p('PLAN_LEAD',P.ob('.today-lead').textContent.trim());
P.p('PLAN_LABELS',P.all('.today-card .tc-l').map(function(b){return b.textContent.trim()}).join('/'));

// ---- data-on 与「箭头在不在」必须成对。
//      只断言 data-on 会漏掉"属性写了、样式没跟上"；只断言箭头会漏掉反过来的。
//      离线态用 display:none 收箭头，不用 opacity —— 那会把正文对比度一起拉下去 ----
P.p('CARD_ON',P.all('.today-card').map(function(a){return a.dataset.on}).join(','));
P.p('ARROW_MATCH',(function(){
  var bad=[];
  P.all('.today-card').forEach(function(a){
    var g=a.querySelector('.tc-go');
    var shown=!!g&&P.cs(g,'display')!=='none';
    if(shown!==(a.dataset.on==='1'))bad.push(a.dataset.k);
  });
  return bad.length?'MISMATCH:'+bad.join('|'):'yes';
})());

// ---- 卡上的数字不许是另算的一份：直接和底层口径对 ----
P.p('DUE_MATCH',(function(){
  var n=+P.ob('[data-k="due"] .tc-n').textContent.trim();
  return n===__bench.revStats().due?'yes':'MISMATCH '+n;
})());
P.p('QUIZ_MATCH',(function(){
  var n=+P.ob('[data-k="quiz"] .tc-n').textContent.trim();
  return n===__bench.revStats().doneEx?'yes':'MISMATCH '+n;
})());
P.p('NEXT_MATCH',(function(){
  var a=P.ob('[data-k="next"]'), nx=null, done=__bench.getState().done;
  __bench.items().forEach(function(i){ if(!nx&&!done[i.id])nx=i; });
  if(!nx)return a.dataset.on==='0'?'yes':'MISMATCH none';
  return a.getAttribute('href')==='#/'+nx.id&&a.dataset.on==='1'?'yes':'MISMATCH '+nx.id;
})());
// 渲染层没有对 todayPlan 做二次加工：四张卡的 数字/去处/开关 三项逐一相符
P.p('PLAN_VS_BENCH',(function(){
  var d=__bench.todayPlan(), dom=P.all('.today-card');
  if(d.items.length!==dom.length)return 'LEN';
  for(var i=0;i<d.items.length;i++){
    if(String(d.items[i].n)!==dom[i].querySelector('.tc-n').textContent.trim())return 'N'+i;
    if(d.items[i].href!==dom[i].getAttribute('href'))return 'H'+i;
    if(String(d.items[i].on?1:0)!==dom[i].dataset.on)return 'O'+i;
  }
  return 'yes';
})());
/* 毕业卡：只断言"它和 gradProgress 是同一份数"，不写死 9 这种内容事实——
   内容一变（比如加一个毕业项目）这里就会假红。 */
P.p('GRAD_SHOW_MATCH',(function(){
  var g=__bench.gradProgress(), c=P.ob('.today-card[data-k="grad"]');
  return !!c===g.show ? 'yes':'NO-BAD';
})());
P.p('GRAD_CARD',(function(){
  var c=P.ob('.today-card[data-k="grad"]');
  if(!c) return __bench.gradProgress().show?'MISSING':'absent-ok';
  var g=__bench.gradProgress();
  var n=c.querySelector('.tc-n').textContent.trim();
  if(n!==g.n+'/'+g.t) return 'N:'+n;
  if(c.getAttribute('href')!=='#/'+g.id) return 'H:'+c.getAttribute('href');
  if(c.dataset.on!=='1') return 'ON';
  if(c.dataset.done!==(g.full?'1':'0')) return 'DONE';
  return 'yes';
})());
// 「该复习」这个数只有一个出处：徽章、统计条、计划卡必须同时一致
P.p('TRIO_DUE',[P.ob('#reviewBadge').textContent.trim(),
  P.ob('[data-k="due"] .tc-n').textContent.trim(),
  String(__bench.revStats().due)].join(','));

// ---- 布局与无障碍 ----
P.p('OVF',P.ovf());
P.p('SMALL',P.small());
P.p('CT_LEAD',P.contrast('.today-lead'));
P.p('CT_DATE',P.contrast('.today-date'));
P.p('CT_N',P.contrast('.tc-n'));
P.p('CT_L',P.contrast('.tc-l'));
P.p('CT_NOTE',P.contrast('.tc-note'));
P.p('CT_SWEEP',P.contrastSweep());
P.p('NO_HSCROLL',document.documentElement.scrollWidth<=document.documentElement.clientWidth+1?'yes':'NO-BAD');

// ---- 深色下重扫一遍 ----
P.key('d');
await P.wait(350);
P.p('DARK_CT_SWEEP',P.contrastSweep());
P.p('DARK_CT_N',P.contrast('.tc-n'));
P.p('DARK_CT_NOTE',P.contrast('.tc-note'));
P.key('d');
await P.wait(300);

// ---- 点卡片要真的落到位（放最后：点完页面就换了）----
P.ob('[data-k="due"]').click();
await P.wait(600);
P.p('CLICK_HASH',location.hash);
P.p('CLICK_PAGE',P.all('.tabs').length>0?'review':'other');
"""

# ---- 毕业项目（三选一）：一组页面、三张清单各自记账 ----
# 页面 id 不写死：从 __bench.items() 里按 kind 反查，slug 改了也不会假红。
GRAD_UI = r"""
await P.ready('ol.hw-list');
await P.wait(320);

var grad = __bench.items().filter(function(x){return x.kind==='grad'})[0];
P.p('GRAD_EXISTS', !!grad);
P.p('GRAD_ID', grad?grad.id:'none');
P.p('GRAD_LABEL', __bench.kindTag(grad||{}));
P.p('GRAD_NOUN', __bench.hwNoun(grad||{}));

var body = P.ob('#lessonBody');
var lists = P.all('ol.hw-list', body);
var items = P.all('ol.hw-list > li', body);
P.p('LISTS', lists.length);
P.p('ITEMS', items.length);
P.p('PER_LIST', lists.map(function(l){
  return l.querySelectorAll(':scope > li').length
}).join(','));
// 每张清单各自从 01 起编号（视觉上的号靠 CSS counter，不是全局号）
P.p('COUNTER_RESET', lists.map(function(l){return P.cs(l,'counterReset')}).join(','));

// 一页多张清单：id 必须**全页唯一且连续**。否则三组清单的第 1 项会挤在
// 同一个 id 上，勾一组等于勾三组。
var ids = items.map(function(li){return li.id});
P.p('IDS', ids.join(','));
P.p('IDS_N', ids.length);
P.p('IDS_UNIQUE', (new Set(ids)).size);
P.p('IDS_SEQ', (grad && ids.join(',')===ids.map(function(_,i){
  return grad.id+':'+i
}).join(','))?'yes':'NO-BAD');
P.p('IDS_INDEX', (grad?__bench.hwIndex().filter(function(x){
  return x.itemId===grad.id
}):[]).map(function(x){return x.id}).join(','));
P.p('IDS_DOM_EQ_INDEX', (function(){
  var idx=(grad?__bench.hwIndex().filter(function(x){return x.itemId===grad.id}):[])
    .map(function(x){return x.id}).join(',');
  return idx===ids.join(',')?'yes':'NO-BAD';
})());

// 回归：tasks 规则曾经把 `<ol>` 拼成 `<ol class="hw-list">>`，
// 页面上会多出一个游离的 '>'。列表里不该有任何裸文本。
P.p('STRAY_GT', lists.filter(function(l){
  var f=l.firstChild;
  return f && f.nodeType===3 && String(f.nodeValue).indexOf('>')>=0;
}).length);

// 三组验收标准各自的进度芯片
var pills = P.all('.grad-pill', body);
P.p('PILLS', pills.length);
P.p('PILL_N', pills.map(function(p){return p.dataset.n}).join(','));
P.p('PILL_T', pills.map(function(p){return p.dataset.t}).join(','));
P.p('PILL_FULL', pills.map(function(p){return p.dataset.full}).join(','));
P.p('PILL_TXT', pills.map(function(p){return p.textContent.trim()}).join('|'));
P.p('PILL_IN_H3', pills.filter(function(p){return p.parentNode.tagName==='H3'}).length);
P.p('PILL_GROUP', pills.map(function(p){return p.dataset.group}).join(','));

// 页头：口径与文案（这一页说的是「验收」，不是「作业」）
P.p('HW_TXT', (P.ob('#hwTxt')||{}).textContent||'none');
P.p('HW_STUCK', (P.ob('#hwStuck')||{}).textContent||'none');
P.p('HW_GAUGE_LABEL', (P.ob('.lesson-head .gauge span')||{}).textContent||'none');
P.p('CHIPS', P.all('.lesson-head .chip').map(function(c){
  return c.textContent.replace(/\s+/g,' ').trim()
}).join(' | '));
P.p('EXPAND_BTN', P.ob('#expandAll')?'present':'absent');
P.p('DONE_BTN', P.ob('#doneBtn')?'present':'absent');
P.p('CRUMB', (P.ob('.crumbs > span')||{}).textContent||'');

// ---- 勾一条：只有它所属的那组该变 ----
var target = items[2];
target.querySelector('.hw-tick input').click();
await P.wait(320);
var p2 = P.all('.grad-pill', body);
P.p('AFTER_N', p2.map(function(p){return p.dataset.n}).join(','));
P.p('AFTER_FULL', p2.map(function(p){return p.dataset.full}).join(','));
P.p('AFTER_TXT', p2[0].textContent.trim());
P.p('AFTER_OTHERS_TXT', p2.slice(1).map(function(p){return p.textContent.trim()}).join('|'));
P.p('AFTER_HWTXT', (P.ob('#hwTxt')||{}).textContent||'none');
P.p('AFTER_STORED', JSON.stringify(__bench.getState().hw[ids[2]]));

// 再点一次 = 记录型，可撤销：满格的芯片必须退回未达成
target.querySelector('.hw-tick input').click();
await P.wait(320);
var p3 = P.all('.grad-pill', body);
P.p('UNDO_FULL', p3.map(function(p){return p.dataset.full}).join(','));
P.p('UNDO_TXT', p3[0].textContent.trim());
P.p('UNDO_STORED', String(__bench.markGet(ids[2])));

// 项目任务和作业共用一张表：总数、守恒式都要对得上
P.p('HW_TOTAL', __bench.revStats().hwTotal);
P.p('CONSERVE', __bench.revStats().poolHw+'+'+__bench.revStats().hwDone
  +'+'+__bench.revStats().hwTodo);

P.p('OVF',P.ovf());
P.p('SMALL',P.small());
P.p('CT_PILL',P.contrast('.grad-pill'));
P.p('CT_PILL_FULL',P.contrast('.grad-pill[data-full="1"]'));
P.p('CT_HW',P.contrast('ol.hw-list > li'));
P.p('CT_SWEEP',P.contrastSweep());
P.p('NO_HSCROLL',document.documentElement.scrollWidth<=document.documentElement.clientWidth+1?'yes':'NO-BAD');

P.blur();
P.key('d');
await P.wait(360);
P.p('DARK_CT_PILL',P.contrast('.grad-pill'));
P.p('DARK_CT_PILL_FULL',P.contrast('.grad-pill[data-full="1"]'));
P.p('DARK_CT_SWEEP',P.contrastSweep());
P.key('d');
await P.wait(300);
P.p('THEME_BACK',document.documentElement.dataset.theme==='light'?'yes':'NO-BAD');
"""

# ---- 「按目标选方向」：静态对照表 → 可点的卡片 ----
# 断言的重点不是"卡片长什么样"，而是**卡片内容有没有真的来自那张表**，
# 以及**href 指到的页面确实存在且是方向页**。
PICKER_UI = r"""
await P.ready('.pick-grid');
await P.wait(320);

var body = P.ob('#lessonBody');
P.p('GRID', P.ob('.pick-grid', body)?'present':'absent');
// 表格应当被卡片取代，而不是两样并存
P.p('TABLE_LEFT', P.all('table', body).length);
// 卡片必须排在正文最前——原表格就在那儿，挪到别处会让"先看目标"变成"先读长文"
P.p('GRID_FIRST', P.all(':scope > *', body)[0]===P.ob('.pick-grid', body)?'yes':'NO-BAD');
var cards = P.all('.pick-card', body);
P.p('CARDS', cards.length);
P.p('DIRS', cards.map(function(c){return c.dataset.dir}).join(','));
P.p('LETTERS', P.all('.pick-card .pick-dir b', body).map(function(b){
  return b.textContent.trim()
}).join(','));
P.p('NAMES', P.all('.pick-card .pick-name', body).map(function(d){
  return d.textContent.trim()
}).join('|'));
P.p('GOALS', P.all('.pick-card .pick-goal', body).map(function(g){
  return g.textContent.trim()
}).join('|'));
P.p('WHY_N', P.all('.pick-card .pick-why', body).filter(function(w){
  return w.textContent.trim().length>3
}).length);
P.p('GO_TXT', P.all('.pick-card .pick-go', body).map(function(g){
  return g.textContent.trim()
}).join('|'));

// 每张卡指向的页面必须真实存在，而且真的是方向页——不是"随便挂个链接"
var hrefs = cards.map(function(c){return c.getAttribute('href')});
P.p('FIRST_HREF', hrefs[0]||'');
P.p('HREF_N', (new Set(hrefs)).size);
P.p('HREF_KINDS', hrefs.map(function(h){
  var id=String(h).replace(/^#\//,'');
  var it=__bench.items().filter(function(x){return x.id===id})[0];
  return it?it.kind:'MISSING';
}).join(','));
P.p('HREF_LETTERS', hrefs.map(function(h){
  var id=String(h).replace(/^#\//,'');
  var it=__bench.items().filter(function(x){return x.id===id})[0];
  return it?String(it.no).toLowerCase():'?';
}).join(','));

P.p('COLS', P.cs(P.ob('.pick-grid'),'gridTemplateColumns').split(' ').length);
P.p('TITLE', (P.ob('.lesson-head h1')||{}).textContent||'');
P.p('LABEL', __bench.kindTag(__bench.items().filter(function(x){
  return x.kind==='picker'})[0]||{}));
// 这一页没有答案也没有作业，那两个控件不该出现
P.p('EXPAND_BTN', P.ob('#expandAll')?'present':'absent');
P.p('HW_GAUGE', P.ob('#hwTxt')?'present':'absent');
P.p('DONE_BTN', P.ob('#doneBtn')?'present':'absent');

/* ---- 就地展开 ----------------------------------------------------------
   卡片点下去不跳页，而是在它自己下方长出一块，里面是**那张方向页的**
   路线 / 核心知识点 / 示例 / 练习题——而且那几道练习题是**真的能勾**的，
   勾了跟课时页一个口径（同一张 hw 表）。
   下面每条都成对：先认"结构落地了"，再认"由此派生的样子/数字跟上了"。 */

// 初始态：五张卡一张都不该是展开的，展开区也只该是空壳
P.p('X_OPEN0', P.all('.pick-item[data-open="1"]', body).length);
P.p('X_VISIBLE0', P.all('.pick-x', body).filter(function(m){return !m.hidden}).length);
P.p('X_EMPTY0', P.all('.pick-x', body).filter(function(m){return !m.children.length}).length);
P.p('ARIA0', P.all('.pick-card[aria-expanded="false"]', body).length);

var it0 = P.all('.pick-item', body)[0];
var card0 = P.ob('.pick-card', it0);
var x0 = P.ob('.pick-x', it0);
// 展开区必须挂在**卡片自己那一格**里，否则宽屏下会重排整行
P.p('X_IN_ITEM', x0 && x0.closest('.pick-item')===it0 ? 'yes':'NO-BAD');
P.click(card0);
await P.wait(420);

/* 宽屏多列时，展开区**不许压在邻格上**——量矩形相交，不靠肉眼。
   同排的另一张卡要么在展开区右边，要么被挤到下一行；重叠就是布局坏了。 */
P.p('X_NO_COVER', (function(){
  var r=x0.getBoundingClientRect();
  return P.all('.pick-item', body).filter(function(t){
    if(t===it0) return false;
    var q=t.getBoundingClientRect();
    var vOverlap = Math.min(r.bottom,q.bottom)-Math.max(r.top,q.top);
    var hOverlap = Math.min(r.right,q.right)-Math.max(r.left,q.left);
    return vOverlap>2 && hOverlap>2;
  }).length;
})());
// 展开区不许超出它所在那一格的右边界
P.p('X_WITHIN_ITEM', (function(){
  var r=x0.getBoundingClientRect(), q=it0.getBoundingClientRect();
  return r.right<=q.right+1.5 ? 'yes':'NO-BAD';
})());
// 诊断用：把三个宽度摆出来，看是谁没跟上谁
P.p('X_W', [Math.round(x0.getBoundingClientRect().width),
            Math.round(it0.getBoundingClientRect().width),
            Math.round(card0.getBoundingClientRect().width)].join('/'));
P.p('X_X', [Math.round(x0.getBoundingClientRect().left),
            Math.round(it0.getBoundingClientRect().left),
            Math.round(card0.getBoundingClientRect().left)].join('/'));
// 同排邻居的顶边必须与它齐平——展开只该撑高本行，不该把邻居顶下去
P.p('X_ROW_ALIGNED', (function(){
  var q=it0.getBoundingClientRect();
  return P.all('.pick-item', body).filter(function(t){
    if(t===it0) return false;
    return Math.abs(t.getBoundingClientRect().top-q.top)<2;
  }).length ? 'yes':'NO-BAD';
})());

P.p('OPEN1', it0.dataset.open);
P.p('CARD_OPEN1', card0.dataset.open);
// 数据 + 派生属性成对：data-open 写了，aria-expanded 和 hidden 也要跟上
P.p('ARIA1', card0.getAttribute('aria-expanded'));
P.p('X_SHOWN1', x0.hidden===false ? 'yes':'NO-BAD');
// 展开是**就地**的：路由一个字没动（页面没跳走）
P.p('STAY_HASH', location.hash.indexOf('s4-')>0 ? 'yes':'NO-BAD');
P.p('ONLY_ONE_OPEN', P.all('.pick-item[data-open="1"]', body).length);
P.p('X_COUNT', P.all('.pick-x', body).length);
P.p('ITEM_N', P.all('.pick-item', body).length);
P.p('X_TICKS', P.all('.pick-x .hw-tick', it0).length);
P.p('X_STUCK', P.all('.pick-x .hw-stuck', it0).length);
// 展开出来的笔记区是"课文那几节"，不是随便一段文字
P.p('X_H4', P.all('.pick-x h4.mini-title', it0).map(function(h){
  return h.textContent.trim()}).join('|'));
P.p('X_CODE', P.all('.pick-x .hl', it0).length);
P.p('X_CODEBAR', P.all('.pick-x .hl .hl-bar', it0).length);
P.p('X_LI', P.all('.pick-x ol.hw-list > li', it0).length);
P.p('X_PROG', (P.ob('.pick-x #pxProg', it0)||{}).textContent||'');
P.p('X_LINK', (P.ob('.pick-x .pick-x-link', it0)||{}).getAttribute('href')||'');

/* 展开区里的作业 id 必须与「全局索引」对得上——否则勾了不进错题本/自测。
   这里断言的是 **id 集合相等**，不是数量相等：数量对而 id 错位是更隐蔽的 bug。 */
var xIds = P.all('.pick-x ol.hw-list > li', it0).map(function(li){return li.id;});
P.p('X_IDS', xIds.join(','));
P.p('X_IDS_IN_INDEX', xIds.every(function(id){
  return __bench.hwIndex().some(function(h){return h.id===id;});
}) ? 'yes':'NO-BAD');
// 反过来：这些 id 在全局索引里必须只出现一次（重复登记会让计数翻倍）
P.p('X_IDS_UNIQUE', xIds.filter(function(id){
  return __bench.hwIndex().filter(function(h){return h.id===id;}).length!==1;
}).length);
// 展开区里的 id 不许和页面别处的 id 撞（撞了勾一个等于勾两个）
P.p('X_ID_DOM_DUP', xIds.filter(function(id){
  return document.querySelectorAll('[id="'+id+'"]').length!==1;
}).length);
// 本页没有别的作业，所以全局口径不该因为展开而变
P.p('HW_TOTAL_STABLE', __bench.hwIndex().length);
// 回传全局 id 清单，供汇总脚本做"就地展开的题确实在全局口径里"这条跨口径检查
P.p('_hwids', __bench.hwIndex().map(function(h){return {'id':h.id}}));

// ---- 就地勾选：同一张表、同一个口径 ----
// 种子已经预置了两种态（0 勾过、1 卡住），先认"渲染时就把它们画对了"
P.p('SEED_STATES', P.all('.pick-x ol.hw-list > li', it0).map(function(l){
  return l.dataset.state}).join(','));
P.p('SEED_CHECKED', P.all('.pick-x .hw-tick input', it0).map(function(b){
  return b.checked?'1':'0'}).join(','));
P.p('SEED_PROG', (P.ob('.pick-x #pxProg', it0)||{}).textContent||'');
// 「已做 x / n」的 x 必须来自底层标记，不是自己另数一遍
P.p('SEED_PROG_MATCH', (function(){
  var t=/已做 (\d+) \/ (\d+)/.exec((P.ob('.pick-x #pxProg', it0)||{}).textContent||'');
  if(!t)return 'NO-PARSE';
  var li=P.all('.pick-x ol.hw-list > li', it0);
  var done=li.filter(function(l){return l.dataset.state==='done'}).length;
  return (+t[1]===done && +t[2]===li.length) ? 'yes':'NO-BAD';
})());
// 卡住那条必须仍然写着 aria-pressed（数据与派生属性成对）
P.p('SEED_STUCK_ARIA', P.all('.pick-x .hw-stuck', it0).map(function(b){
  return b.getAttribute('aria-pressed')}).join(','));

// 把第 3 条勾上：三种态应当同页并存
var li3 = P.all('.pick-x ol.hw-list > li', it0)[2];
var box3 = P.ob('.hw-tick input', li3);
box3.checked = true; box3.dispatchEvent(new Event('change',{bubbles:true}));
await P.wait(320);
P.p('X3_STATE', li3.dataset.state);
P.p('X_STATES3', P.all('.pick-x ol.hw-list > li', it0).map(function(l){
  return l.dataset.state}).join(','));
P.p('X_PROG_DONE', (P.ob('.pick-x #pxProg', it0)||{}).textContent||'');
P.p('X_STORED', JSON.stringify(__bench.getState().hw));
P.p('X_HWDONE', __bench.revStats().hwDone);
P.p('X_REV_N', __bench.revStats().hwTodo);
// 卡住也走同一条路，而且点第二次＝改主意（撤销），不是把题删了。
// ⚠️ 必须按**下标**取那颗按钮：`.hw-stuck` 的第一个属于第 1 条，不是种子标的那条。
var li1 = P.all('.pick-x ol.hw-list > li', it0)[1];
var stk = P.ob('.hw-stuck', li1);
P.p('UNSTUCK_BEFORE', li1.dataset.state);
P.click(stk);
await P.wait(320);
P.p('UNSTUCK_STATE', li1.dataset.state);
P.p('UNSTUCK_ARIA', stk.getAttribute('aria-pressed'));
P.p('UNSTUCK_STORED', JSON.stringify(__bench.getState().hw));

/* ---- 收起的三个入口：点卡片 / 再点卡片 / 展开区里按 Esc ----
   ⚠️ Esc 的监听挂在**展开区自己**身上，所以不能对着 document 发键——
   那种发法是"谁都没听见"，会让"没反应"看起来像"行为错了"。 */
P.p('ESC_NAV_WORKS', (function(){
  // 先确认这颗节点真的在文档里、真的能被聚焦——否则下面的 Esc 是空放
  x0.focus();
  return document.activeElement===x0 ? 'yes':'NO-BAD';
})());
x0.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));
await P.wait(340);
P.p('ESC_CLOSED', it0.dataset.open);
P.p('ESC_HIDDEN', x0.hidden===true ? 'yes':'NO-BAD');
P.p('ESC_ARIA', card0.getAttribute('aria-expanded'));
P.p('ESC_TXT', (P.ob('.pick-go-t', it0)||{}).textContent||'');
// 再点开、再点关：内容不许越堆越多，勾选也不许被清掉
P.click(card0);
await P.wait(340);
P.click(card0);
await P.wait(340);
P.p('REOPEN_N', P.all('.pick-x', body).length);
P.p('REOPEN_H4', P.all('.pick-x h4.mini-title', it0).length);
P.p('REOPEN_TICKS', P.all('.pick-x .hw-tick', it0).length);
P.p('REOPEN_MARK_KEPT', P.all('.pick-x ol.hw-list > li', it0)
  .filter(function(l){return l.dataset.state!=='todo'}).length);

// ---- 一次性口令：从别处跳到某方向并就地展开 ----
P.p('PENDING0', String(__bench.getPendingDir()));
__bench.pickDir('c');
await P.wait(900);
P.p('JUMP_HASH', location.hash);
P.p('JUMP_OPEN', P.all('.pick-item[data-open="1"]', P.ob('#lessonBody')).length);
P.p('JUMP_DIR', P.all('.pick-item[data-open="1"]', P.ob('#lessonBody')).map(function(x){
  return x.dataset.dir}).join(','));
P.p('JUMP_CONSUMED', String(__bench.getPendingDir()));
P.p('JUMP_TICKS', P.all('.pick-item[data-open="1"] .pick-x .hw-tick', P.ob('#lessonBody')).length);
// 口令用完就得清掉：留着的话下次进本页会莫名其妙展开一格
P.p('JUMP_NOT_LATCHED', (function(){
  __bench.render();
  return P.all('.pick-item[data-open="1"]').length;
})());

/* ⚠️ 上面那句 render() 把 #lessonBody 整个换掉了，先前抓的 body 已经是**游离节点**。
   不重新取的话，后面所有以 body 为根的查询都在读旧树——会看到
   "body 里数得到、document 里数不到"这种自相矛盾的结果。 */
body = P.ob('#lessonBody');

P.p('OVF',P.ovf());
P.p('SMALL',P.small());
P.p('CT_GOAL',P.contrast('.pick-goal'));
P.p('CT_DIR',P.contrast('.pick-dir'));
P.p('CT_WHY',P.contrast('.pick-why'));
P.p('CT_GO',P.contrast('.pick-go'));
P.p('CT_SWEEP',P.contrastSweep());
P.p('NO_HSCROLL',document.documentElement.scrollWidth<=document.documentElement.clientWidth+1?'yes':'NO-BAD');

// 深色下的对比度要有一格展开着才量得到——上面 JUMP_NOT_LATCHED 整页重渲染过，
// 展开区已被销毁。这里**明确地**挑一张还没展开的卡点开，别靠"再点一次"，
// 那样点到已展开的那张会把它收起来，于是量到一片 none。
var it2 = P.all('.pick-item[data-open="0"]', body)[0];
P.click(P.ob('.pick-card', it2));
await P.wait(400);
P.p('DARK_HAS_X', P.all('.pick-x:not([hidden])', body).length);
P.p('DARK_X_BUILT', P.all('.pick-x:not([hidden]) .pick-x-h', body).length);
P.blur();
P.key('d');
await P.wait(400);
P.p('DARK_THEME', document.documentElement.dataset.theme);
P.p('DARK_X_N', document.querySelectorAll('.pick-x-h h3').length);
P.p('DARK_X_VIS', P.all('.pick-x-h h3', body).filter(function(e){
  return !!e.getBoundingClientRect().width}).length);
P.p('CT_X_H', P.contrast('.pick-x-h h3'));
P.p('CT_X_PROG', P.contrast('.pick-x-prog'));
P.p('CT_X_MT', P.contrast('.pick-x h4.mini-title'));
P.p('CT_X_LINK', P.contrast('.pick-x-link'));
P.p('CT_X_CODE', P.contrast('.pick-x .hl code'));
P.p('DARK_CT_SWEEP', P.contrastSweep());
P.key('d');
await P.wait(300);
"""

# 窄屏版：一张卡片宽、每条验收标准都占满一行，这里只看"有没有塌成单列、
# 有没有把页面撑破"。功能态由 grad 场景在宽屏下验，两边不重复数数。
GRAD_NARROW_UI = r"""
await P.ready('ol.hw-list');
await P.wait(320);
P.p('LISTS',P.all('ol.hw-list').length);
P.p('ITEMS',P.all('ol.hw-list > li').length);
P.p('PILLS',P.all('.grad-pill').length);
P.p('LIST_W',Math.round(P.ob('ol.hw-list').getBoundingClientRect().width));
P.p('CONTENT_W',Math.round(P.ob('#contentRoot').getBoundingClientRect().width));
P.p('TICK_W',Math.round(P.ob('.hw-tick').getBoundingClientRect().width));
P.p('STUCK_H',Math.round(P.ob('.hw-stuck').getBoundingClientRect().height));
P.p('H3_WRAP',(function(){
  var h=P.ob('#lessonBody h3'), p=P.ob('.grad-pill');
  if(!h||!p)return 'none';
  return p.getBoundingClientRect().right<=h.getBoundingClientRect().right+1.5
    ? 'inside':'OVERFLOW';
})());
P.p('OVF',P.ovf());
P.p('SMALL',P.small());
P.p('NO_HSCROLL',document.documentElement.scrollWidth<=document.documentElement.clientWidth+1?'yes':'NO-BAD');
P.p('CT_SWEEP',P.contrastSweep());
"""

# 只埋 2 个真实存在的例题 id；ex-s1-l1-0 指向「运行效果」块（不是题），
# 另外 3 个是"内容改版后残留"的幽灵 id —— 这 4 条都必须被忽略
EX_STALE_SEED = {
    "done": {}, "hw": {}, "miles": {},
    "ex": {
        "ex-s1-l1-1": -1,
        "ex-s1-l3-1": -1,
        "ex-s1-l1-0": -1,
        "ex-ghost-l99-0": -1,
        "ex-ghost-l99-1": -1,
        "ex-another-ghost-7": -1,
    },
    "time": {}, "theme": None, "last": None,
}


def _day(n):
    """相对今天算日期，让档期场景在任何一天跑都成立。"""
    return (date.today() + timedelta(days=n)).isoformat()


def hw_stuck_seed():
    """一条卡住的作业（连对 4 次、还欠着 2 天 —— 再答对一次就毕业），
    外加一道欠着的例题，用来看两类欠债混排时会不会被区别对待。"""
    return {
        "done": {}, "hw": {"s1-l1:0": -1}, "miles": {},
        "ex": {"ex-s1-l1-1": -1},
        "rev": {
            "s1-l1:0": {"l": 4, "due": _day(-2), "n": 5},
            "ex-s1-l1-1": {"l": 1, "due": _day(-1), "n": 2},
        },
        "time": {}, "theme": None, "last": None,
    }


def spaced_seed():
    """四道错题，分别压在不同档位、不同到期日。

    真实存在的例题 id 是这节课里排除了「运行效果」块之后的序号——
    s1-l1 的第 0 个块是效果图，所以它的题是 -1 / -2。
    """
    return {
        "done": {}, "hw": {}, "miles": {},
        "ex": {
            "ex-s1-l1-1": -1,   # 连对 1 次，欠了 2 天
            "ex-s1-l1-2": -1,   # 连对 2 次，今天到期
            "ex-s1-l2-0": -1,   # 连对 1 次，3 天后
            "ex-s1-l3-0": -1,   # 连对 4 次，今天到期 —— 再对一次就毕业
        },
        "rev": {
            "ex-s1-l1-1": {"l": 1, "due": _day(-2), "n": 2},
            "ex-s1-l1-2": {"l": 2, "due": _day(0), "n": 3},
            "ex-s1-l2-0": {"l": 1, "due": _day(3), "n": 1},
            "ex-s1-l3-0": {"l": 4, "due": _day(0), "n": 5},
        },
        "time": {}, "theme": None, "last": None,
    }


def quiz_seed():
    """s1 的 16 道例题全部标成「已掌握」，另有两道压在错题本里当 T2。

    这样「范围 s1 + 只例题」抽出来的 5 道必然全是 T0（最久没被检验的
    那一层），"答错就退回错题本"的断言才不依赖随机顺序。

    s1-l1 的第 0 个 details.answer 是「运行效果」块，它占号但不是题，
    所以那节课的例题 id 是 -1 / -2，其余课是 -0 / -1。
    """
    ids = []
    for l in range(1, 9):
        base = "ex-s1-l%d-" % l
        ids += [base + "1", base + "2"] if l == 1 else [base + "0", base + "1"]
    ex = {i: 1 for i in ids}
    ex["ex-s2-l9-0"] = -1
    ex["ex-s2-l9-1"] = -1
    return {
        "done": {"s1-l%d" % l: 1 for l in range(1, 9)},
        "hw": {}, "miles": {}, "ex": ex,
        "rev": {
            "ex-s2-l9-0": {"l": 1, "due": _day(0), "n": 1},
            "ex-s2-l9-1": {"l": 0, "due": _day(-1), "n": 1},
        },
        "time": {}, "theme": None, "last": None,
    }


def today_seed():
    """首页「今日计划」用：让前三张卡有活、第四张没活。

    这张种子刻意不是"全亮"——「连续学习」留空（time 表里没有今天），
    于是 data-on 的两种取值同时出现在一页里，箭头与开关成对的那条断言
    才有区分度；全亮的话把 [data-on] 写死成 "1" 也能蒙混过关。

    前四课都标完成，所以"下一个知识点"必然落在 s1-l5；
    三道已掌握例题让第三张卡非零，两道错题让第一张卡非零。
    """
    return {
        "done": {"s1-l%d" % l: 1 for l in range(1, 5)},
        "hw": {"s1-l1:0": 1, "s1-l2:0": -1},
        "miles": {},
        "ex": {
            "ex-s1-l1-1": 1, "ex-s1-l1-2": 1, "ex-s1-l2-0": 1,
            "ex-s1-l3-0": -1, "ex-s1-l4-0": -1,
        },
        "rev": {
            "ex-s1-l3-0": {"l": 1, "due": _day(0), "n": 1},
            "ex-s1-l4-0": {"l": 0, "due": _day(-1), "n": 1},
            "s1-l2:0": {"l": 2, "due": _day(6), "n": 2},
        },
        "time": {}, "theme": None, "last": "s1-l4",
    }


def grad_seed():
    """毕业项目页：三组验收标准各留一种状态。

    刻意让 data-full 的两种取值**同页出现**——① 2/3、② 只标了「卡住」、③ 3/3。
    全填满或全空的话，把 data-full 写死成单个值也能蒙混过关；② 里那条「卡住」
    同时让页头的「卡住」计数非零，一张种子验两件事。

    验收标准的 id 是 <页面 id>:<全局序号>——① 占 0-2、② 占 3-5、③ 占 6-8。
    这个"全局"很关键：按清单内序号编的话，三张清单的第 1 项会撞在同一个 id 上。
    """
    hw = {
        "s4-毕业项目-三选一:0": 1,
        "s4-毕业项目-三选一:1": 1,
        "s4-毕业项目-三选一:3": -1,     # 卡住：进错题本，今天就该复习
        "s4-毕业项目-三选一:6": 1,
        "s4-毕业项目-三选一:7": 1,
        "s4-毕业项目-三选一:8": 1,
    }
    return {
        "done": {"s1-l1": 1}, "hw": hw, "miles": {}, "ex": {},
        "rev": {"s4-毕业项目-三选一:3": {"l": 0, "due": _day(0), "n": 0}},
        "time": {}, "theme": None, "last": None,
    }


def picker_seed():
    """「选方向」页：给方向练习题预置状态。

    刻意让**同一张展开区里三种态同时出现**（勾过 / 卡住 / 没表态）——
    id 形状与课时页一致：<方向页 id>:<本页第几项>，就地展开区里也是从 0 起。
    不写死"第几题是什么"，只铺状态，断言的形状由探针按关系去验。
    """
    return {
        "done": {"s4-dira": 1, "s1-l1": 1},
        "hw": {"s4-dira:0": 1, "s4-dira:1": -1},
        "miles": {}, "ex": {},
        "rev": {"s4-dira:1": {"l": 0, "due": _day(0), "n": 0}},
        "time": {}, "theme": None, "last": None,
    }


# 「该毕业了」提示的场景：三种情形各存一份种子，逐个验。
# 这里是**内容不可知**的写法——课程 id 只用来铺种子，断言一律走 gradProgress()。
def course_done_seed():
    """正课 + 阶段项目全完成、毕业项目一项没勾 → 该出现「该做毕业项目了」。
    判定必须忽略「附录」「怎么选方向」这类拓展页，否则它们永远不勾、这张卡永远不出现。"""
    done = {}
    for i in range(1, 9):
        done["s1-l%d" % i] = 1
    for i in range(9, 17):
        done["s2-l%d" % i] = 1
    for i in range(17, 25):
        done["s3-l%d" % i] = 1
    done.update({"s1-p": 1, "s2-p": 1, "s3-p": 1})
    # 刻意**不**勾 s4-附录-通用自查清单 / s4-怎么选方向：它们不该挡住毕业卡
    return {
        "done": done, "hw": {}, "miles": {}, "ex": {}, "rev": {},
        "time": {}, "theme": None, "last": "s3-p",
    }


def grad_full_seed():
    """毕业项目九项验收全过 → 卡片翻成「已达成」，lead 换成收尾那句。
    九项分三组（三选一），所以"全过"是按**整页口径**算的。"""
    return {
        "done": {}, "miles": {}, "ex": {}, "rev": {}, "time": {},
        "hw": {("s4-毕业项目-三选一:%d" % i): 1 for i in range(9)},
        "theme": None, "last": "s4-毕业项目-三选一",
    }


GRADPLAN_UI = r"""
await P.ready('.today');
await P.wait(500);

var g=__bench.gradProgress(), c=P.ob('.today-card[data-k="grad"]');
P.p('SHOW', g.show?'1':'0');
P.p('N', g.n); P.p('T', g.t);
P.p('FULL', g.full?'1':'0');
P.p('STARTED', g.started?'1':'0');
P.p('COURSE_DONE', g.courseDone?'1':'0');
P.p('STUCK', g.stuck);
P.p('LEFT', g.left);
// 卡片必须真的在，而且三项（数字/去处/开关）与 gradProgress 相符
P.p('CARD', c?'present':'absent');
P.p('CARD_N', c?c.querySelector('.tc-n').textContent.trim():'');
P.p('CARD_LABEL', c?c.querySelector('.tc-l').textContent.trim():'');
P.p('CARD_NOTE', c?c.querySelector('.tc-note').textContent.trim():'');
P.p('CARD_HREF', c?c.getAttribute('href'):'');
P.p('CARD_DONE', c?(c.dataset.done||''):'');
P.p('CARD_ON', c?c.dataset.on:'');
// 数字就是 n/t，不许是另算的一份
P.p('N_MATCH', (c && c.querySelector('.tc-n').textContent.trim()===g.n+'/'+g.t)?'yes':'NO-BAD');
P.p('DONE_MATCH', (c && c.dataset.done===(g.full?'1':'0'))?'yes':'NO-BAD');
// 卡序：毕业卡必须排在「下一项」之后、「复核」之前——它是里程碑，不是日常项
P.p('KEYS', P.all('.today-card').map(function(a){return a.dataset.k}).join(','));
P.p('GRAD_BEFORE_QUIZ', (function(){
  var ks=P.all('.today-card').map(function(a){return a.dataset.k});
  var gi=ks.indexOf('grad'), ni=ks.indexOf('next'), qi=ks.indexOf('quiz');
  return (gi<0 || (gi>ni && gi<qi)) ? 'yes':'NO-BAD';
})());
P.p('CARD_N', P.all('.today-card').length);
P.p('LEAD', P.ob('.today-lead').textContent.trim());
P.p('OVF',P.ovf());
P.p('SMALL',P.small());
P.p('CT_N',P.contrast('.today-card[data-k="grad"] .tc-n'));
P.p('CT_L',P.contrast('.today-card[data-k="grad"] .tc-l'));
P.p('CT_NOTE',P.contrast('.today-card[data-k="grad"] .tc-note'));
P.p('CT_SWEEP',P.contrastSweep());
P.p('NO_HSCROLL',document.documentElement.scrollWidth<=document.documentElement.clientWidth+1?'yes':'NO-BAD');
P.blur();
P.key('d');
await P.wait(400);
P.p('DARK_CT_N',P.contrast('.today-card[data-k="grad"] .tc-n'));
P.p('DARK_CT_L',P.contrast('.today-card[data-k="grad"] .tc-l'));
P.p('DARK_CT_NOTE',P.contrast('.today-card[data-k="grad"] .tc-note'));
P.p('DARK_CT_SWEEP',P.contrastSweep());
P.key('d');
await P.wait(300);
// 点它要真的落到毕业项目页
P.ob('.today-card[data-k="grad"]').click();
await P.wait(700);
P.p('CLICK_HASH',location.hash);
P.p('CLICK_PILLS',P.all('.grad-pill').length);
"""

# 阶段页（#/s1…#/s4）。补这个场景是因为：套件原先的 17 个场景从不访问阶段页，
# 于是「0 控制台错误」只对 34 个页面里的 17 条路由成立——阶段页上抛的
# TypeError（refreshProgress 里 .stage-card 没筛 data-stage）就这么躲过去了。
# 场景的 hash 直接落在 #/s2，所以启动期渲染的报错会由通用的 __BOOT_ERR 兜住；
# 场景体内再走完 4 个阶段页，覆盖"换页之后"的报错与焦点归位。
STAGE_UI = r"""
await P.ready('#contentRoot');
await P.wait(300);

// 期望值从应用自己的数据里推，不写死在探针里
var ids = COURSE.stages.map(function(s){return s.id});

var rows = [];
var ovfAll = [], smallAll = [], ctAll = [], hscrollBad = 0;
for (var i=0;i<ids.length;i++){
  location.hash = '#/' + ids[i];
  await P.wait(260);
  var st = COURSE.stages[i];
  var h1 = P.ob('#contentRoot h1');
  var act = document.activeElement || {};
  var statuses = P.all('.stage-card .sc-pct').map(function(e){return e.textContent.trim()});
  rows.push({
    id: ids[i],
    want: st.name,
    h1: h1 ? h1.textContent.trim() : '',
    focus: (act.tagName||'') + '#' + (act.id||'-'),
    cards: P.all('.stage-card').length,
    // 课时卡的状态只该是「已完成 / 未开始」；出现 "n / m" 就说明
    // refreshProgress 把"阶段合计"写到课时卡上了
    stageTotalsOnCard: statuses.filter(function(s){return /^\d+\s*\/\s*\d+$/.test(s)}).length,
    homeGrid: P.all('#stageGrid').length
  });
  // 四页各扫一遍几何与对比度，合并上报（每页单独报会变成 4 组同名指标）
  ovfAll = ovfAll.concat(P.ovf());
  smallAll = smallAll.concat(P.small());
  ctAll = ctAll.concat(P.contrastSweep());
  if (document.documentElement.scrollWidth > document.documentElement.clientWidth + 1) hscrollBad++;
}

P.p('STAGE_ROWS', JSON.stringify(rows));
P.p('STAGE_N', rows.length);
// 路由真的解析到了对应的阶段（而不是悄悄回落到首页）
P.p('STAGE_H1_MATCH', rows.every(function(r){return r.h1===r.want}));
P.p('STAGE_NO_HOME_FALLBACK', rows.every(function(r){return r.homeGrid===0}));
P.p('STAGE_CARDS_POS', rows.every(function(r){return r.cards>0}));
P.p('STAGE_NO_TOTAL_ON_CARD', rows.every(function(r){return r.stageTotalsOnCard===0}));
// 换页后焦点要落到正文（render() 末尾那步；它原先被抛出的异常中断了）
P.p('STAGE_FOCUS', rows.map(function(r){return r.focus}).join(','));
P.p('STAGE_FOCUS_OK', rows.every(function(r){return r.focus==='MAIN#contentRoot'}));
P.p('__ERRS_AFTER_WALK', (window.__errs||[]).length);
P.p('NO_HSCROLL', hscrollBad===0 ? 'yes' : ('NO-BAD x'+hscrollBad));
P.p('OVF', ovfAll.slice(0,12));
P.p('SMALL', smallAll.slice(0,20));
P.p('CT_SWEEP', ctAll.slice(0,12));
"""


SCEN = {
    "home": ("", 1440, 1000, HOME_UI),
    "lesson": ("#/s3-l17", 1440, 1000, LESSON_UI),
    "exopen": ("#/s1-l1", 1440, 1000, EX_OPEN_UI),
    "review": ("#/review", 1440, 1000, REVIEW_UI),
    "spaced": ("#/review", 1440, 1000, SPACED_UI),
    "records": ("#/records", 1440, 1100, RECORDS_UI),
    "quiz": ("#/quiz", 1440, 1100, QUIZ_UI),
    "today": ("", 1440, 1040, TODAY_UI),
    "exstale": ("#/review", 1440, 1000, EX_STALE_UI),
    "hwstuck": ("#/review", 1440, 1000, HW_STUCK_UI),
    "recmin": ("#/records", 1440, 1100, r"""
await P.ready('.hm');
await P.wait(400);
P.p('OK',1);
P.p('HM_CELLS',P.all('.hm-c').length);
P.p('REC_CARDS',P.all('.rec-grid').length);
P.p('BENCH',typeof window.__bench);
"""),
    "narrow430": ("", 430, 1000, NARROW_UI + NARROW_TAIL),
    "narrow768": ("", 768, 1000, NARROW_UI + NARROW_TAIL),
    # 阶段四闭环：毕业项目（三选一，三张清单各自记账）与「按目标选方向」。
    # 路由用的是页面 slug；万一标题改了，这里会落到首页、断言整片变红——
    # 是"响亮地失败"，不会静默通过。
    "grad": ("#/s4-毕业项目-三选一", 1440, 1100, GRAD_UI),
    "grad430": ("#/s4-毕业项目-三选一", 430, 1100, GRAD_NARROW_UI),
    "picker": ("#/s4-怎么选方向", 1440, 1050, PICKER_UI),
    # 「该毕业了」提示：课程走完那一刻出现，毕业项目满格后翻成「已达成」
    "gradplan": ("", 1440, 1080, GRADPLAN_UI),
    "gradplanFull": ("", 1440, 1080, GRADPLAN_UI),
    # 阶段页：hash 落在 #/s2，所以启动期报错由 __BOOT_ERR 兜住
    "stage": ("#/s2", 1440, 1100, STAGE_UI),
}

BUDGET = 150000

# 需要在应用启动前预写 localStorage 的场景：(存储键, 数据或产数据的函数)
# exstale 特意写进 v2，顺带把「老版本数据自动迁移」这条路径也一起测了
SEEDS = {
    "exstale": ("py-path-v2", EX_STALE_SEED),
    "spaced": ("py-path-v3", spaced_seed),
    "hwstuck": ("py-path-v3", hw_stuck_seed),
    "quiz": ("py-path-v3", quiz_seed),
    "today": ("py-path-v3", today_seed),
    "grad": ("py-path-v3", grad_seed),
    "grad430": ("py-path-v3", grad_seed),
    "picker": ("py-path-v3", picker_seed),
    "gradplan": ("py-path-v3", course_done_seed),
    "gradplanFull": ("py-path-v3", grad_full_seed),
}


def run(scenario: str) -> dict:
    frag, w, h, ui = SCEN[scenario]
    tag = uuid.uuid4().hex[:6]
    html = SRC.read_text(encoding="utf-8")
    html = html.replace("</head>", ERR_HOOK + "</head>", 1)
    if scenario in SEEDS:
        key, data = SEEDS[scenario]
        if callable(data):
            data = data()
        pre = ('<script>try{localStorage.setItem("%s",%s)}catch(e){}</script>'
               % (key, json.dumps(json.dumps(data, ensure_ascii=False))))
        html = html.replace("</head>", pre + "</head>", 1)
    html = html.replace("</body>", "<script>" + BASE + ui + TAIL + "</script></body>", 1)
    page = B / ("_probe_%s-%s.html" % (scenario, tag))
    page.write_text(html, encoding="utf-8")
    prof = B / ("_prof_%s-%s" % (scenario, tag))

    cmd = [
        CHROME, "--headless=new", "--disable-gpu", "--no-first-run",
        "--no-default-browser-check", "--hide-scrollbars",
        "--disable-smooth-scrolling", "--force-device-scale-factor=1",
        "--allow-file-access-from-files",
        "--user-data-dir=" + str(prof),
        "--window-size=%d,%d" % (w, h),
        "--virtual-time-budget=%d" % BUDGET,
        "--dump-dom",
        page.as_uri() + frag,
    ]
    r = subprocess.run(cmd, capture_output=True)
    dom = r.stdout.decode("utf-8", errors="replace")
    m = re.search(r"PROBE_BEGIN([A-Za-z0-9+/=]+)PROBE_END", dom, re.S)
    src = "comment"
    if not m:
        m = re.search(r"PROBEB64([A-Za-z0-9+/=]+)PROBEEND", dom, re.S)
        src = "mirror"
    metrics = {}
    if m:
        try:
            metrics = json.loads(base64.b64decode(m.group(1)).decode("utf-8"))
        except Exception:
            metrics["__decode_error"] = traceback.format_exc()[-400:]
    else:
        # 探针没回话，把当时的 DOM 留下来排查
        (B / ("_domfail_%s.html" % scenario)).write_text(dom, encoding="utf-8")
        eb = re.search(r'id="__errbox"[^>]*>([^<]*)<', dom, re.S)
        metrics["__ERRBOX"] = eb.group(1)[:600] if eb else "(无 __errbox)"
        metrics["__PROBE_SCRIPT_PRESENT"] = "PROBE_BEGIN" in dom
        metrics["__PROBE_ALIVE_DIV"] = 'id="__probe_out"' in dom
    return {
        "scenario": scenario,
        "viewport": "%dx%d" % (w, h),
        "dom_kb": round(len(dom) / 1024, 1),
        "has_probe": bool(m),
        "source": src if m else "-",
        "metrics": metrics,
        "stderr_tail": r.stderr.decode("utf-8", errors="replace")[-400:],
    }


if __name__ == "__main__":
    names = sys.argv[1:] or list(SCEN.keys())
    summary = {}
    for n in names:
        try:
            res = run(n)
        except Exception:
            res = {"scenario": n, "fatal": traceback.format_exc()[-800:]}
        (B / ("_browser_%s.json" % n)).write_text(
            json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        summary[n] = {
            "probe": res.get("has_probe"),
            "n": len(res.get("metrics") or {}),
        }
    (B / "_browser_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
