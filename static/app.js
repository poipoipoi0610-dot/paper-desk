import {paragraphScrollPosition} from './sync.js';
import {openImage} from './viewer.js';
import {setupLibrary} from './library.js';
const $ = id => document.getElementById(id);
const state = {token:'',papers:[],paper:null,page:1,sync:localStorage.getItem('paperDesk.sync')!=='false',zoom:1,selected:null,chatBusy:false,account:null};
let polling = false, importBusy=false, scrollOwner=null, scrollTimer, toastTimer;
const esc = s => String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function toast(text){$('toast').textContent=text;$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').hidden=true,5000);}
async function api(path,body,options={}){
 const res=await fetch(path,{...options,method:options.method||(body!==undefined?'POST':'GET'),headers:{...(body!==undefined?{'Content-Type':'application/json','X-Paper-Token':state.token}:{}),...options.headers},body:body!==undefined?JSON.stringify(body):options.body});
 const result=await res.json();if(!res.ok)throw new Error(result.error||'请求失败');return result;
}
function showError(node,e){node.textContent=e.message||String(e);node.hidden=false;}
function paperUrl(suffix=''){return `/api/papers/${state.paper.id}${suffix}`;}
function selectedModel(){return $('modelSelect').value||null;}
function statusName(status){return ({complete:'已完成',processing:'生成中',queued:'等待中',error:'待重试',paused:'已暂停',ready:'待生成'})[status]||status;}

async function bootstrap(){
 try{const b=await api('/api/bootstrap');state.token=b.token;state.papers=b.papers;renderLibrary();const last=localStorage.getItem('paperDesk.last');const p=b.papers.find(p=>p.id===last)||b.papers[0];if(p)await openPaper(p.id);}
 catch(e){toast(e.message);}
 refreshAccount();setInterval(pollPaper,2200);
}
async function refreshAccount(){
 try{state.account=await api('/api/account');const a=state.account;$('accountBtn').classList.toggle('connected',a.connected);$('accountBtn').querySelector('span').textContent=a.connected?'ChatGPT 已连接':'连接 ChatGPT';$('chatStatus').textContent=a.connected?'ChatGPT · 本机 Codex':'尚未连接';document.querySelector('.connection-dot').classList.toggle('connected',a.connected);$('accountDetail').innerHTML=`<div class="account-card">${a.connected?'<strong>已连接你的 ChatGPT 账号</strong><br>'+esc(a.email||'账号已登录')+(a.plan?'<br>套餐：'+esc(a.plan):''):esc(a.error||'请先登录 ChatGPT，完成后刷新连接状态。')}</div>`;$('loginBtn').hidden=a.connected;
 if(a.connected&&$('modelSelect').options.length===1){const models=(await api('/api/models')).models;for(const m of models){const o=document.createElement('option');o.value=m.model;o.textContent=m.name+ (m.default?' · 默认':'');$('modelSelect').append(o);}}
 }catch(e){$('accountBtn').querySelector('span').textContent='连接暂不可用';showError($('accountDetail'),e);}
}
async function openPaper(id){
 if(state.chatBusy&&state.paper?.id!==id){toast('请等当前回答完成后再切换论文');return;}
 const p=await api(`/api/papers/${id}`);state.paper=p;state.selected=null;$('selectionBar').hidden=true;state.page=Number(localStorage.getItem(`paperDesk.page.${id}`))||1;state.page=Math.min(state.page,p.pageCount);localStorage.setItem('paperDesk.last',id);$('empty').hidden=true;$('reader').hidden=false;renderMeta();renderPages();renderFramework();renderMessages();jumpPage(state.page);$('libraryDialog').close();
}
function renderMeta(){
 $('compactPaperTitle').textContent=state.paper.titleZh||state.paper.title;$('compactPaperTitle').title=state.paper.title;$('paperDetailsBtn').hidden=false;
 const p=state.paper;$('paperTitle').textContent=p.titleZh||p.title;$('paperSubtitle').textContent=p.titleZh?p.title:p.filename;$('paperLabel').textContent=`文献阅读 / ${p.pageCount} 页 / 本机文献库`;$('jobStage').textContent=p.stage;$('jobCount').textContent=`${p.completedPages} / ${p.pageCount} 页`;$('jobProgress').max=p.pageCount;$('jobProgress').value=p.completedPages;$('jobDot').classList.toggle('running',['processing','queued'].includes(p.status));$('jobAction').hidden=p.status==='complete';$('jobAction').textContent=['processing','queued'].includes(p.status)?'暂停':(p.status==='ready'?'开始生成':'继续生成');$('jobError').hidden=!p.error;if(p.error)$('jobError').textContent=p.error;$('pageTotal').textContent=p.pageCount;$('pageInput').max=p.pageCount;$('originalDownload').href=paperUrl('/original.pdf');$('download').setAttribute('aria-disabled',String(!p.exportReady));if(p.exportReady)$('download').href=paperUrl('/chinese.pdf');else $('download').removeAttribute('href');$('download').download=(p.titleZh||p.title).slice(0,100)+'-中文.pdf';$('footerNote').textContent=p.contextNote||'点击原文段落定位中文译稿 · 原图与独立公式保留';setPageIndicator(state.page);
}
function renderLibrary(){
 $('libraryList').replaceChildren();if(!state.papers.length){$('libraryList').innerHTML='<p class="muted">还没有论文，先导入第一篇。</p>';return;}for(const p of state.papers){const b=document.createElement('button');b.className='library-item';b.innerHTML=`<strong>${esc(p.titleZh||p.title)}</strong><small>${p.pageCount} 页 · 已译 ${p.completedPages} 页 · ${esc(statusName(p.status))}</small>`;b.onclick=()=>openPaper(p.id).catch(e=>toast(e.message));$('libraryList').append(b);}
}
async function pollPaper(){
 if(polling||!state.paper||document.hidden)return;polling=true;const id=state.paper.id;
 try{const p=await api(`/api/papers/${id}`);if(state.paper?.id!==id)return;const old=state.paper;state.paper=p;if(p.updatedAt!==old.updatedAt){renderMeta();if(JSON.stringify(p.framework)!==JSON.stringify(old.framework)||p.status!==old.status)renderFramework();for(let i=0;i<p.pages.length;i++){if(p.pages[i].translated!==old.pages[i].translated||JSON.stringify(p.pages[i].blocks.map(b=>b.zh))!==JSON.stringify(old.pages[i].blocks.map(b=>b.zh)))updateTranslatedPage(p.pages[i]);}if(!state.chatBusy&&p.chat.length!==old.chat.length)renderMessages();}}
 catch(e){$('jobStage').textContent='本机服务暂时无响应，正在重连…';}finally{polling=false;}
}

function createPage(page,side){
 const card=document.createElement('article');card.className='page-card';card.dataset.page=page.number;card.dataset.side=side;card.dataset.paper=state.paper.id;card.style.width=`${state.zoom*100}%`;card.style.setProperty('--ratio',`${page.width/page.height}`);
 const paper=document.createElement('div');paper.className='page-paper';card.append(paper);
 if(side==='original'||page.translated){
  const image=document.createElement('img');image.alt=`${side==='original'?'原文':'中文译稿'}第 ${page.number} 页`;image.className='loading';image.dataset.src=paperUrl(`/page/${page.number}/${side}.svg`);image.decoding='async';image.onclick=()=>openPageImage(page,side);const loading=document.createElement('span');loading.className='loading-label';loading.textContent='正在加载页面…';paper.append(loading,image);image.onload=()=>{image.classList.remove('loading');loading.remove();};image.onerror=()=>{loading.textContent='页面加载失败，点击重试';loading.style.cursor='pointer';loading.onclick=()=>{image.src=image.dataset.src+'?retry='+Date.now();};};
  const spots=document.createElement('div');spots.className='hotspots';for(const b of page.blocks){if(!b.translate)continue;const button=document.createElement('button');button.className='hotspot';button.dataset.block=b.id;button.setAttribute('aria-label',`${side==='original'?'定位中文译稿':'定位原文'} · 第 ${page.number} 页段落：${(side==='original'?b.text:b.zh||b.text).slice(0,50)}`);button.title=side==='original'?'点击定位中文译稿对应段落':'点击定位原文对应段落';const [x0,y0,x1,y1]=b.bbox;Object.assign(button.style,{left:`${x0/page.width*100}%`,top:`${y0/page.height*100}%`,width:`${(x1-x0)/page.width*100}%`,height:`${(y1-y0)/page.height*100}%`});button.onclick=()=>selectBlock(b,page.number,side,button);spots.append(button);}paper.append(spots);
 }else{paper.innerHTML=`<div class="pending-page"><strong>第 ${page.number} 页译稿待生成</strong><span>生成后会自动出现在这里。<br>现在可以阅读原文或向 GPT 提问。</span></div>`;}
 const caption=document.createElement('div');caption.className='page-caption';caption.innerHTML=`<span>${side==='original'?'原文':'AI 中文译稿'} · ${page.number} / ${state.paper.pageCount}</span><span>${side==='chinese'?(page.warnings.length?'有排版提示 · 点击段落查看':'原图与独立公式保留'):''}</span>`;if(side==='chinese'&&page.warnings.length)caption.title=page.warnings.map(w=>w.replaceAll('完整译文见逐段对照','点击对应段落查看完整译文')).join('\n');if(side==='original'||page.translated){const view=document.createElement('button');view.className='page-expand';view.textContent='⤢ 放大本页';view.onclick=()=>openPageImage(page,side);caption.append(view);}card.append(caption);return card;
}
function openPageImage(page,side){openImage({url:paperUrl(`/page/${page.number}/${side}.svg`),width:page.width,height:page.height,title:`${side==='original'?'原文':'中文译稿'} · 第 ${page.number} 页`,detail:'矢量页面 · 可放大查看文字与图表'});}
const figureCache=new Map();
async function loadFigures(card){
 if(!card||card.dataset.figuresLoaded)return;card.dataset.figuresLoaded='loading';
 const id=card.dataset.paper,pn=Number(card.dataset.page),side=card.dataset.side,key=`${id}:${pn}`;
 try{
  if(!figureCache.has(key))figureCache.set(key,api(`/api/papers/${id}/page/${pn}/figures`).then(r=>r.figures).catch(e=>{figureCache.delete(key);throw e;}));
  const figures=await figureCache.get(key);if(!card.isConnected)return;
  const page=state.paper.pages[pn-1],spots=card.querySelector('.hotspots');
  for(const figure of figures){const [x0,y0,x1,y1]=figure.bbox,b=document.createElement('button');b.className='figure-hotspot';b.setAttribute('aria-label',`打开第 ${pn} 页${figure.label}并放大`);b.innerHTML='<span>⤢ 点击放大</span>';Object.assign(b.style,{left:`${x0/page.width*100}%`,top:`${y0/page.height*100}%`,width:`${(x1-x0)/page.width*100}%`,height:`${(y1-y0)/page.height*100}%`});b.onclick=e=>{e.stopPropagation();openImage({url:`/api/papers/${id}/page/${pn}/figure/${figure.id}/${side}.svg`,width:x1-x0,height:y1-y0,title:`${figure.label} · 第 ${pn} 页`,detail:`${side==='original'?'原文':'中文译稿'} · 保留原图与矢量线条`});};spots.append(b);}
  card.dataset.figuresLoaded='true';
 }catch(e){delete card.dataset.figuresLoaded;}
}
const observers=[];
function lazyLoad(){
 observers.forEach(o=>o.disconnect());observers.length=0;for(const root of [$('sourceScroll'),$('translationScroll')]){const observer=new IntersectionObserver(entries=>{for(const e of entries)if(e.isIntersecting){const im=e.target;if(!im.src)im.src=im.dataset.src;loadFigures(im.closest('.page-card'));observer.unobserve(im);}},{root,rootMargin:'900px 0px'});root.querySelectorAll('img[data-src]').forEach(im=>{if(!im.src||!im.closest('.page-card').dataset.figuresLoaded)observer.observe(im);});observers.push(observer);}
}
function renderPages(){
 for(const [id,side] of [['sourceScroll','original'],['translationScroll','chinese']]){const fragment=document.createDocumentFragment();state.paper.pages.forEach(p=>fragment.append(createPage(p,side)));$(id).replaceChildren(fragment);}lazyLoad();highlight();updateParagraphNote();
}
function updateTranslatedPage(page){const root=$('translationScroll');const anchor=readAnchor(root);const card=root.querySelector(`[data-page="${page.number}"]`);if(card)card.replaceWith(createPage(page,'chinese'));lazyLoad();highlight();applyAnchor(root,anchor);updateParagraphNote();}
function highlight(){document.querySelectorAll('[data-block]').forEach(el=>{const selected=el.dataset.block===state.selected?.id;el.classList.toggle('selected',selected);el.setAttribute('aria-pressed',String(selected));});}
function updateParagraphNote(){
 const selection=state.selected,page=selection&&state.paper.pages[selection.page-1],block=page?.blocks.find(b=>b.id===selection.id);
 const overflow=block?.zh&&page.warnings.some(w=>w.startsWith(block.id+'：')||w.startsWith(block.id+':'));
 $('paragraphNote').hidden=!overflow;
 if(overflow){$('paragraphNoteTitle').textContent=`p.${page.number} · 本段完整译文`;$('paragraphNoteText').textContent=block.zh;}
 if(block){state.selected={...block,page:page.number};$('selectionText').textContent=`引用 p.${page.number}：${block.zh||block.text}`;}
}
function selectBlock(block,pageNumber,side,button){
 state.selected={...block,page:pageNumber};highlight();$('selectionBar').hidden=false;updateParagraphNote();
 const source=$(side==='original'?'sourceScroll':'translationScroll'),target=$(side==='original'?'translationScroll':'sourceScroll');
 const page=state.paper.pages[pageNumber-1],card=target.querySelector(`[data-page="${pageNumber}"]`),paper=card.querySelector('.page-paper');
 const bounds=target.getBoundingClientRect(),paperBounds=paper.getBoundingClientRect();
 const position=paragraphScrollPosition(block,page,{
  paperTop:localTop(paper,target),paperLeft:paperBounds.left-bounds.left+target.scrollLeft,
  paperWidth:paperBounds.width,paperHeight:paperBounds.height,viewportWidth:target.clientWidth,viewportHeight:target.clientHeight,
  scrollLeft:target.scrollLeft,maxScrollLeft:target.scrollWidth-target.clientWidth,maxScrollTop:target.scrollHeight-target.clientHeight,
  offsetTop:button.getBoundingClientRect().top-source.getBoundingClientRect().top,
 });
 // Explicit navigation works with either scroll preference; never pull the clicked pane away.
 scrollOwner='jump';clearTimeout(scrollTimer);target.scrollTop=position.top;target.scrollLeft=position.left;
 const image=paper.querySelector('img[data-src]');if(image&&!image.src)image.src=image.dataset.src;
 setPageIndicator(pageNumber);scrollTimer=setTimeout(()=>scrollOwner=null,150);
 toast(side==='original'&&!page.translated?`第 ${pageNumber} 页译稿尚未生成，已定位到该页`:`已定位${side==='original'?'中文译稿':'原文'}对应段落 · 可向 GPT 提问`);
}

function localTop(element,root){return element.getBoundingClientRect().top-root.getBoundingClientRect().top+root.scrollTop;}
function readAnchor(root){
 if(!state.paper)return {page:1,y:0};const cards=[...root.children];const line=root.scrollTop+8;let card=cards.find(c=>localTop(c,root)+c.offsetHeight>line)||cards.at(-1);if(!card)return {page:1,y:0};const page=Number(card.dataset.page);
 const paper=card.querySelector('.page-paper');return {page,y:Math.max(0,Math.min(1,(line-localTop(paper,root))/Math.max(1,paper.offsetHeight)))};
}
function applyAnchor(root,anchor){
 if(!state.paper)return;const card=root.querySelector(`[data-page="${anchor.page}"]`);if(!card)return;
 const paper=card.querySelector('.page-paper');root.scrollTop=Math.max(0,localTop(paper,root)+paper.offsetHeight*anchor.y-8);
}
function setPageIndicator(page){if(!state.paper)return;state.page=page;$('pageInput').value=page;$('leftPosition').textContent=`p.${state.sync?page:readAnchor($('sourceScroll')).page}`;$('rightPosition').textContent=`p.${state.sync?page:readAnchor($('translationScroll')).page}`;$('currentPageState').textContent=state.paper.pages[page-1]?.translated?'本页已译':'本页待译';$('prevPage').disabled=page<=1;$('nextPage').disabled=page>=state.paper.pageCount;localStorage.setItem(`paperDesk.page.${state.paper.id}`,page);}
function jumpPage(page){if(!state.paper)return;page=Math.max(1,Math.min(state.paper.pageCount,Number(page)||1));scrollOwner='jump';for(const root of [$('sourceScroll'),$('translationScroll')]){const card=root.querySelector(`[data-page="${page}"]`);if(card)root.scrollTop=localTop(card,root)-18;}setPageIndicator(page);clearTimeout(scrollTimer);scrollTimer=setTimeout(()=>scrollOwner=null,150);}
for(const root of [$('sourceScroll'),$('translationScroll')]){
 root.addEventListener('wheel',()=>{scrollOwner=root.id;},{passive:true});root.addEventListener('pointerdown',()=>{scrollOwner=root.id;},{passive:true});root.addEventListener('keydown',()=>{scrollOwner=root.id;});
 root.addEventListener('scroll',()=>{if(!state.paper||scrollOwner&&scrollOwner!==root.id)return;scrollOwner=root.id;const anchor=readAnchor(root);setPageIndicator(anchor.page);if(state.sync)applyAnchor(root.id==='sourceScroll'?$('translationScroll'):$('sourceScroll'),anchor);clearTimeout(scrollTimer);scrollTimer=setTimeout(()=>scrollOwner=null,130);},{passive:true});
}
function updateSync(){$('syncBtn').classList.toggle('active',state.sync);$('syncBtn').setAttribute('aria-pressed',String(state.sync));$('syncBtn').textContent=state.sync?'⇅ 滚动已锁定':'⇅ 独立滚动';}
function showSide(side){$('framework').hidden=side!=='framework';$('chatPanel').hidden=side!=='chat';for(const name of ['framework','chat']){$(name+'Tab').classList.toggle('selected',side===name);$(name+'Tab').setAttribute('aria-pressed',String(side===name));}if(side==='chat')$('chatInput').focus();}
function renderFramework(){
 const frame=state.paper.framework,root=$('framework');root.replaceChildren();if(!frame){const active=['processing','queued'].includes(state.paper.status);root.innerHTML=`<div class="blank-side">${active?'<div class="spinner"></div>':''}<strong>${active?'正在梳理论文的整体思路':'开始生成论文框架与中文译稿'}</strong><span>${active?'研究动机、实现框架、实验与结论会在这里出现。你可以先读原文。':'原文已准备好。点击生成后，将通过你的 ChatGPT 账号分析和翻译这篇论文。'}</span>${active?'':'<button id="startFromFramework" class="primary">生成框架与译稿 →</button>'}</div>`;if(!active)$('startFromFramework').onclick=()=>$('jobAction').click();return;}
 const lead=document.createElement('p');lead.className='framework-lead';lead.textContent=frame.oneLine;root.append(lead);const keys=[['motivation','研究动机'],['method','整体实现'],['experiments','验证与实验'],['results','主要结果'],['limitations','边界与局限']];keys.forEach(([key,name],i)=>{const sec=document.createElement('section');sec.className='frame-section'+(key==='limitations'?' limits':'');sec.innerHTML=`<h3><small>${String(i+1).padStart(2,'0')}</small>${name}</h3>`;for(const item of frame[key]){const p=document.createElement('p');p.className='frame-item';p.append(document.createTextNode(item.text+' '));for(const page of item.pages){const b=document.createElement('button');b.className='cite';b.textContent=`p.${page} ↗`;b.onclick=()=>jumpPage(page);p.append(b);}sec.append(p);}root.append(sec);});
}
function addMessage(role,text){const el=document.createElement('div');el.className=`message ${role}`;const label=document.createElement('span');label.className='speaker';label.textContent=role==='user'?'你':'GPT · 论文伴读';const content=document.createElement('div');content.className='message-content';el.append(label,content);$('messages').append(el);setMessage(content,text);return content;}
function setMessage(node,text){node.replaceChildren();const parts=String(text).split(/(\[p\.\s*\d+(?:\s*[-–—]\s*\d+)?\])/g);for(const part of parts){const m=part.match(/^\[p\.\s*(\d+)(?:\s*[-–—]\s*(\d+))?\]$/);if(m&&Number(m[1])>=1&&Number(m[1])<=state.paper.pageCount){const b=document.createElement('button');b.className='cite';b.textContent=`p.${m[1]}${m[2]?'–'+m[2]:''} ↗`;b.onclick=()=>jumpPage(Number(m[1]));node.append(b);}else{const chunks=part.split(/(\*\*[^*]+\*\*)/g);for(const chunk of chunks){if(chunk.startsWith('**')&&chunk.endsWith('**')){const strong=document.createElement('strong');strong.textContent=chunk.slice(2,-2);node.append(strong);}else node.append(document.createTextNode(chunk));}}}}
function renderMessages(){const root=$('messages');root.replaceChildren();if(!state.paper.chat.length){root.innerHTML='<div class="chat-welcome"><h3>一起读懂这篇论文。</h3><p>可以问整篇论文，也可以先在左侧点选一段。回答中的页码可以直接返回原文。</p></div>';for(const question of ['用三句话说清这篇论文解决了什么问题','方法的核心步骤是什么？','实验充分证明了作者的结论吗？']){const b=document.createElement('button');b.className='suggestion';b.textContent=question;b.onclick=()=>{$('chatInput').value=question;$('chatInput').focus();};root.append(b);}}else state.paper.chat.forEach(m=>addMessage(m.role,m.text));root.scrollTop=root.scrollHeight;}
async function sendChat(e){
 e.preventDefault();if(!state.paper||state.chatBusy)return;const message=$('chatInput').value.trim();if(!message)return;state.chatBusy=true;$('sendChat').disabled=true;$('sendChat').textContent='回答中…';$('messages').querySelector('.chat-welcome')?.remove();$('messages').querySelectorAll('.suggestion').forEach(x=>x.remove());addMessage('user',message);const target=addMessage('assistant','正在阅读相关内容…');$('chatInput').value='';const paperId=state.paper.id;let answer='';
 try{const res=await fetch(`/api/papers/${paperId}/chat`,{method:'POST',headers:{'Content-Type':'application/json','X-Paper-Token':state.token},body:JSON.stringify({message,page:state.page,blockId:state.selected?.id,model:selectedModel()})});if(!res.ok){const data=await res.json();throw new Error(data.error||'发送失败');}const reader=res.body.getReader(),decoder=new TextDecoder();let buffer='';while(true){const {done,value}=await reader.read();buffer+=decoder.decode(value||new Uint8Array(),{stream:!done});const lines=buffer.split('\n');buffer=lines.pop();for(const line of lines){if(!line.trim())continue;const event=JSON.parse(line);if(event.type==='error')throw new Error(event.error);if(event.type==='delta')answer+=event.text;if(event.type==='done')answer=event.text;setMessage(target,answer||'正在阅读相关内容…');$('messages').scrollTop=$('messages').scrollHeight;}if(done)break;}if(!answer)throw new Error('连接中断，未收到完整回答。');if(state.paper.id===paperId)state.paper.chat.push({role:'user',text:message},{role:'assistant',text:answer});}
 catch(e){target.parentElement.classList.add('error');target.textContent=(answer?answer+'\n\n':'')+'未能完成回答：'+e.message;toast(e.message);}
 finally{state.chatBusy=false;$('sendChat').disabled=false;$('sendChat').textContent='发送 ↑';}
}

function openImport(){$('importError').hidden=true;$('importDialog').showModal();}
async function uploadFile(file){
 if(!file)return;if(file.size>64*1024*1024)throw new Error('文件超过 64 MB。');$('importProgress').textContent='正在上传并解析 PDF…';const res=await fetch('/api/upload',{method:'POST',headers:{'Content-Type':'application/pdf','X-Paper-Token':state.token,'X-Filename':encodeURIComponent(file.name),'X-Model':selectedModel()||''},body:file});const data=await res.json();if(!res.ok)throw new Error(data.error);return data.paperId;
}
async function submitImport(e){e.preventDefault();if(importBusy)return;importBusy=true;$('submitImport').disabled=true;$('importError').hidden=true;
 try{const file=$('fileInput').files[0],url=$('urlInput').value.trim();let id;if(file){id=await uploadFile(file);}else if(url){$('importProgress').textContent='正在解析链接并下载论文…';const task=await api('/api/import',{url,model:selectedModel()});for(;;){await new Promise(r=>setTimeout(r,1200));const result=await api('/api/imports/'+task.importId);if(result.status==='error')throw new Error(result.error);if(result.status==='complete'){id=result.paperId;break;}}}else throw new Error('请选择 PDF 或填写论文链接。');await openPaper(id);$('importDialog').close();$('fileInput').value='';$('urlInput').value='';toast('论文已导入，框架与译稿会自动生成');}
 catch(e){showError($('importError'),e);}finally{importBusy=false;$('submitImport').disabled=false;$('importProgress').textContent='';}}

for(const id of ['importBtn','firstImport'])$(id).onclick=openImport;
document.querySelectorAll('[data-close]').forEach(b=>b.onclick=()=>$(b.dataset.close).close());
setupLibrary({api,openPaper,selectedModel,toast,canOpen:()=>{if(state.chatBusy){toast('请等当前回答完成后再切换论文');return false;}return true;},refreshLocal:async()=>{const b=await api('/api/bootstrap');state.token=b.token;state.papers=b.papers;renderLibrary();}});
$('accountBtn').onclick=()=>{$('accountDialog').showModal();refreshAccount();};$('refreshAccount').onclick=refreshAccount;
$('loginBtn').onclick=async()=>{try{$('loginBtn').disabled=true;const login=await api('/api/account/login',{});const url=new URL(login.authUrl);if(!['https:'].includes(url.protocol)||!['auth.openai.com','chatgpt.com'].includes(url.hostname))throw new Error('登录地址异常，请使用 Codex 客户端登录。');const a=document.createElement('a');a.href=url.href;a.target='_blank';a.rel='noopener';a.textContent='点击打开官方 ChatGPT 登录页面 ↗';$('loginLink').replaceChildren(a);window.open(url.href,'_blank','noopener');const timer=setInterval(async()=>{await refreshAccount();if(state.account?.connected){clearInterval(timer);$('loginLink').textContent='登录成功，可以开始阅读。';}},3000);setTimeout(()=>clearInterval(timer),180000);}catch(e){toast(e.message);}finally{$('loginBtn').disabled=false;}};
$('importForm').onsubmit=submitImport;
$('fileInput').onchange=()=>{if($('fileInput').files.length)$('urlInput').value='';};$('urlInput').oninput=()=>{if($('urlInput').value)$('fileInput').value='';};
$('dropzone').ondragover=e=>{e.preventDefault();$('dropzone').classList.add('drag');};$('dropzone').ondragleave=()=>$('dropzone').classList.remove('drag');$('dropzone').ondrop=e=>{e.preventDefault();$('dropzone').classList.remove('drag');if(e.dataTransfer.files.length){$('fileInput').files=e.dataTransfer.files;$('urlInput').value='';}};
$('jobAction').onclick=async()=>{try{const active=['processing','queued'].includes(state.paper.status);await api(paperUrl(active?'/pause':'/start'),{model:selectedModel()});toast(active?'正在暂停，已完成页面会保留':'已加入生成队列');await pollPaper();}catch(e){toast(e.message);}};
$('prevPage').onclick=()=>jumpPage(state.page-1);$('nextPage').onclick=()=>jumpPage(state.page+1);$('pageInput').onchange=()=>jumpPage($('pageInput').value);
$('syncBtn').onclick=()=>{state.sync=!state.sync;localStorage.setItem('paperDesk.sync',state.sync);updateSync();if(state.sync)applyAnchor($('translationScroll'),readAnchor($('sourceScroll')));};
$('zoom').onchange=()=>{const anchor=readAnchor($('sourceScroll'));state.zoom=Number($('zoom').value);document.querySelectorAll('.page-card').forEach(c=>c.style.width=state.zoom*100+'%');requestAnimationFrame(()=>{applyAnchor($('sourceScroll'),anchor);applyAnchor($('translationScroll'),anchor);});};
$('closeParagraphNote').onclick=()=>$('paragraphNote').hidden=true;$('frameworkTab').onclick=()=>showSide('framework');$('chatTab').onclick=()=>showSide('chat');$('chatForm').onsubmit=sendChat;$('chatInput').onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();$('chatForm').requestSubmit();}};$('clearSelection').onclick=()=>{state.selected=null;$('selectionBar').hidden=true;$('paragraphNote').hidden=true;highlight();};
$('paperDetailsBtn').onclick=()=>{const show=$('paperDetails').hidden;$('paperDetails').hidden=!show;$('paperDetailsBtn').setAttribute('aria-expanded',String(show));$('paperDetailsBtn').textContent=show?'收起信息 ⌃':'论文信息 ⌄';};
document.querySelector('.reading-toolbar').insertBefore(document.querySelector('.compact-job'),document.querySelector('.reader-tools'));
updateSync();bootstrap();
