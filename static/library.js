const $ = id => document.getElementById(id);
const esc = s => String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

export function setupLibrary({api, openPaper, refreshLocal, selectedModel, toast, canOpen}) {
 let catalog=null, library='user', collection='', tab=localStorage.getItem('paperDesk.libraryTab')||'zotero';
 let loading=false, opening=false, requestId=0, signature='', shown=50;
 const dialog=$('libraryDialog');

 function setTab(next){
  tab=next;localStorage.setItem('paperDesk.libraryTab',tab);
  for(const name of ['local','zotero']){$(name+'LibraryPanel').hidden=name!==tab;$(name+'LibraryTab').classList.toggle('selected',name===tab);$(name+'LibraryTab').setAttribute('aria-pressed',String(name===tab));}
  if(tab==='zotero')load();else refreshLocal().catch(e=>toast(e.message));
 }

 async function load(force=false){
  const rid=++requestId, selectedLibrary=library;loading=true;$('zoteroRefresh').disabled=true;
  if(!catalog)$('zoteroStatus').textContent='正在连接 Zotero…';
  try{
   const result=await api(`/api/zotero/catalog?library=${encodeURIComponent(library)}${force?'&refresh=1':''}`);
   if(rid!==requestId)return;
   catalog=result;$('zoteroError').hidden=true;$('zoteroStatus').classList.add('connected');
   $('zoteroStatus').textContent=`已连接 · ${catalog.items.length} 篇文献 · ${catalog.collections.length} 个分类 · ${new Date(catalog.syncedAt).toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'})} 更新`;
   const next=JSON.stringify([catalog.serverId,catalog.library,catalog.items,catalog.collections,catalog.libraries]);
   if(next!==signature){signature=next;
    if(collection&&!catalog.collections.some(c=>c.key===collection))collection='';
    $('zoteroLibrary').replaceChildren(...catalog.libraries.map(l=>{const o=document.createElement('option');o.value=l.id;o.textContent=l.name;return o;}));$('zoteroLibrary').value=library;
    renderCollections();renderItems();
   }
  }catch(e){if(rid!==requestId)return;$('zoteroStatus').classList.remove('connected');$('zoteroStatus').textContent='Zotero 暂未连接';$('zoteroError').textContent=e.message;$('zoteroError').hidden=false;if(!catalog||catalog.library!==selectedLibrary)$('zoteroItems').innerHTML='<div class="library-empty">打开 Zotero 并启用本地连接后，点击右上角刷新。<br>已经导入的论文仍可在“本机已导入”中阅读。</div>';}
  finally{if(rid===requestId){loading=false;$('zoteroRefresh').disabled=false;}}
 }

 function descendants(key){const keys=new Set([key]);let changed=true;while(changed){changed=false;for(const c of catalog.collections)if(keys.has(c.parent)&&!keys.has(c.key)){keys.add(c.key);changed=true;}}return keys;}
 function inCollection(item,key){if(!key)return true;const keys=descendants(key);return item.collections.some(k=>keys.has(k));}
 function renderCollections(){
  const root=$('zoteroCollections');root.replaceChildren();
  function button(key,name,depth=0){const b=document.createElement('button');b.className='collection-button'+(key===collection?' selected':'');b.style.paddingLeft=(10+depth*13)+'px';b.setAttribute('aria-pressed',String(key===collection));b.title=name+(key?'（包含子分类）':'');const count=catalog.items.filter(i=>inCollection(i,key)).length;b.innerHTML=`<span>${key?'▱':'▤'} ${esc(name)}</span><small>${count}</small>`;b.onclick=()=>{collection=key;shown=50;renderCollections();renderItems();};root.append(b);}
  button('','全部文献');const visited=new Set();
  function branch(parent,depth){for(const c of catalog.collections.filter(c=>c.parent===parent).sort((a,b)=>a.name.localeCompare(b.name,'zh-CN'))){if(visited.has(c.key))continue;visited.add(c.key);button(c.key,c.name,Math.min(depth,8));branch(c.key,depth+1);}}
  branch(null,0);for(const c of catalog.collections)if(!visited.has(c.key))button(c.key,c.name);
 }

 function renderItems(){
  if(!catalog)return;
  const query=$('zoteroSearch').value.trim().toLowerCase(), pdfOnly=$('zoteroPdfOnly').checked;
  const items=catalog.items.filter(i=>inCollection(i,collection)&&(!pdfOnly||i.pdfs.length)&&(!query||[i.title,i.authors,i.year,i.doi,...i.tags].join(' ').toLowerCase().includes(query))).sort((a,b)=>b.dateAdded.localeCompare(a.dateAdded));
  $('zoteroCollectionName').textContent=catalog.collections.find(c=>c.key===collection)?.name||'全部文献';$('zoteroCount').textContent=`${items.length} 篇${collection?' · 含子分类':''}`;
  const root=$('zoteroItems');root.replaceChildren();
  if(!items.length){root.innerHTML=`<div class="library-empty">${query||pdfOnly?'没有匹配的文献，试试其他关键词或取消筛选。':'这个分类还没有文献。'}</div>`;return;}
  for(const item of items.slice(0,shown)){
   const row=document.createElement('article');row.className='zotero-item';row.innerHTML=`<div class="zotero-item-title"><h3>${esc(item.title)}</h3><span class="tag ${item.pdfs.length?'':'no-pdf'}">${item.pdfs.length?item.pdfs.length+' PDF':'无 PDF'}</span></div><p class="zotero-authors" title="${esc(item.authors)}">${esc([item.authors,item.year].filter(Boolean).join(' · ')||'作者与年份未填写')}</p>`;
   if(item.tags.length){const tags=document.createElement('div');tags.className='zotero-tags';tags.textContent=item.tags.slice(0,4).join(' · ');row.append(tags);}
   const actions=document.createElement('div');actions.className='zotero-item-actions';
   let selected=item.pdfs[0];
   const status=document.createElement('small');status.className='muted';
   const button=document.createElement('button');button.className='small';button.disabled=opening||!selected;
   function update(){button.textContent=selected?.reader?'继续阅读 →':'打开阅读 →';status.textContent=selected?.reader?`已导入 · 已译 ${selected.reader.completedPages} / ${selected.reader.pageCount} 页`:selected?'点击打开原文，可随时开始翻译':'请先在 Zotero 中添加 PDF 附件';}
   if(item.pdfs.length>1){const select=document.createElement('select');select.setAttribute('aria-label','选择 PDF 附件：'+item.title);for(const pdf of item.pdfs){const opt=document.createElement('option');opt.value=pdf.key;opt.textContent=pdf.title+(pdf.filename?' · '+pdf.filename:'');select.append(opt);}select.onchange=()=>{selected=item.pdfs.find(p=>p.key===select.value);update();};select.disabled=opening;actions.append(select);}
   update();actions.append(status,button);row.append(actions);button.onclick=()=>open(item,selected);root.append(row);
  }
  if(items.length>shown){const more=document.createElement('button');more.className='load-more';more.textContent=`加载更多（还有 ${items.length-shown} 篇）`;more.onclick=()=>{shown+=50;renderItems();};root.append(more);}
 }

 async function open(item,attachment){
  if(opening||!attachment||!canOpen())return;
  opening=true;renderItems();$('zoteroHint').textContent='正在读取并解析所选 PDF…';
  try{
   const result=await api('/api/zotero/open',{library,itemKey:item.key,attachmentKey:attachment.key,serverId:catalog.serverId,generate:$('zoteroGenerate').checked,model:selectedModel()});
   let paperId;
   for(let count=0;count<300;count++){
    await new Promise(r=>setTimeout(r,500));const job=await api('/api/imports/'+result.importId);
    if(job.status==='error')throw new Error(job.error);
    if(job.status==='complete'){paperId=job.paperId;break;}
   }
   if(!paperId)throw new Error('解析仍在进行，可稍后在“本机已导入”中查看。');
   await refreshLocal();await openPaper(paperId);signature='';toast('已从 Zotero 打开论文，阅读进度与已有译稿会保留');
  }catch(e){$('zoteroError').textContent=e.message;$('zoteroError').hidden=false;toast(e.message);}
  finally{opening=false;$('zoteroHint').textContent='开启生成后，所选论文文字将发送到 OpenAI。';renderItems();}
 }

 $('libraryBtn').onclick=()=>{dialog.showModal();setTab(tab);};
 $('localLibraryTab').onclick=()=>setTab('local');$('zoteroLibraryTab').onclick=()=>setTab('zotero');
 $('zoteroRefresh').onclick=()=>load(true);
 $('zoteroLibrary').onchange=()=>{library=$('zoteroLibrary').value;collection='';catalog=null;signature='';$('zoteroCollections').replaceChildren();$('zoteroItems').innerHTML='<div class="library-empty">正在读取文库…</div>';load(true);};
 for(const id of ['zoteroSearch','zoteroPdfOnly'])$(id).addEventListener('input',()=>{shown=50;renderItems();});
 setInterval(()=>{if(dialog.open&&tab==='zotero'&&!document.hidden&&!loading&&!opening)load(true);},30000);
}
