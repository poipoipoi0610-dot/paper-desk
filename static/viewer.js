const $ = id => document.getElementById(id);
const dialog=$('imageDialog'), stage=$('imageStage'), canvas=$('imageCanvas'), image=$('imageView');
let view={width:1,height:1,fit:1,zoom:1}, drag=null;

function layout(){
 const width=view.width*view.fit*view.zoom, height=view.height*view.fit*view.zoom;
 image.style.width=width+'px';image.style.height=height+'px';
 canvas.style.width=Math.max(stage.clientWidth,width+48)+'px';
 canvas.style.height=Math.max(stage.clientHeight,height+48)+'px';
 $('imageZoomLabel').textContent=Math.round(view.zoom*100)+'%';
 $('imageZoomOut').disabled=view.zoom<=.25;$('imageZoomIn').disabled=view.zoom>=8;
}
function zoomTo(zoom,x=stage.clientWidth/2,y=stage.clientHeight/2){
 const oldWidth=image.clientWidth,oldHeight=image.clientHeight;
 const fx=(stage.scrollLeft+x-(canvas.clientWidth-oldWidth)/2)/Math.max(1,oldWidth);
 const fy=(stage.scrollTop+y-(canvas.clientHeight-oldHeight)/2)/Math.max(1,oldHeight);
 view.zoom=Math.max(.25,Math.min(8,zoom));layout();
 stage.scrollLeft=(canvas.clientWidth-image.clientWidth)/2+fx*image.clientWidth-x;
 stage.scrollTop=(canvas.clientHeight-image.clientHeight)/2+fy*image.clientHeight-y;
}
function fit(){view.fit=Math.min((stage.clientWidth-48)/view.width,(stage.clientHeight-48)/view.height);view.zoom=1;layout();stage.scrollLeft=0;stage.scrollTop=0;}
export function openImage({url,width,height,title,detail}){
 view={width,height,fit:1,zoom:1};$('imageTitle').textContent=title;$('imageDetail').textContent=detail;
 image.alt=title;image.style.visibility='hidden';$('imageLoading').hidden=false;$('imageLoading').textContent='正在打开清晰原图…';
 image.onload=()=>{image.style.visibility='visible';$('imageLoading').hidden=true;};
 image.onerror=()=>{$('imageLoading').textContent='图片加载失败，请关闭后重试';};
 if(!dialog.open)dialog.showModal();fit();image.src=url;stage.focus();
}
$('imageZoomIn').onclick=()=>zoomTo(view.zoom*1.25);
$('imageZoomOut').onclick=()=>zoomTo(view.zoom/1.25);
$('imageFit').onclick=fit;$('imageClose').onclick=()=>dialog.close();
dialog.addEventListener('close',()=>{drag=null;stage.classList.remove('dragging');image.removeAttribute('src');});
stage.addEventListener('wheel',e=>{e.preventDefault();const r=stage.getBoundingClientRect();zoomTo(view.zoom*Math.exp(-e.deltaY*.002),e.clientX-r.left,e.clientY-r.top);},{passive:false});
stage.addEventListener('dblclick',e=>{const r=stage.getBoundingClientRect();zoomTo(view.zoom>1?1:2,e.clientX-r.left,e.clientY-r.top);});
stage.addEventListener('pointerdown',e=>{if(e.button!==0)return;drag={id:e.pointerId,x:e.clientX,y:e.clientY,left:stage.scrollLeft,top:stage.scrollTop};stage.setPointerCapture(e.pointerId);stage.classList.add('dragging');e.preventDefault();});
stage.addEventListener('pointermove',e=>{if(!drag||drag.id!==e.pointerId)return;stage.scrollLeft=drag.left+drag.x-e.clientX;stage.scrollTop=drag.top+drag.y-e.clientY;});
for(const name of ['pointerup','pointercancel','lostpointercapture'])stage.addEventListener(name,()=>{drag=null;stage.classList.remove('dragging');});
stage.addEventListener('keydown',e=>{if(['+','=','-','0'].includes(e.key)){e.preventDefault();if(e.key==='0')fit();else zoomTo(view.zoom*(e.key==='-'?.8:1.25));}});
// Scrollbars change the stage's content box during zoom; only a window resize
// should refit it, otherwise zoom would immediately snap back to 100%.
window.addEventListener('resize',()=>{if(dialog.open)fit();});
