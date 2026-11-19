import test from 'node:test';
import assert from 'node:assert/strict';
import {paragraphScrollPosition} from '../static/sync.js';
const page={width:600,height:800};
const view={paperTop:1800,paperLeft:12,paperWidth:600,paperHeight:800,viewportWidth:640,viewportHeight:700,scrollLeft:0,maxScrollLeft:0,maxScrollTop:8000,offsetTop:200};
test('a distant paragraph aligns with the clicked paragraph independently of scroll lock',()=>{
 assert.deepEqual(paragraphScrollPosition({bbox:[40,400,560,520]},page,view),{top:2000,left:0});
});
test('200% zoom reveals a right-column paragraph outside the horizontal viewport',()=>{
 assert.deepEqual(paragraphScrollPosition({bbox:[320,400,560,520]},page,{...view,paperWidth:1200,paperHeight:1600,maxScrollLeft:600}),{top:2400,left:508});
});
test('navigation clamps at the first and last page',()=>{
 assert.equal(paragraphScrollPosition({bbox:[0,0,200,100]},page,{...view,paperTop:0}).top,0);
 assert.equal(paragraphScrollPosition({bbox:[0,790,200,800]},page,{...view,maxScrollTop:2000,offsetTop:-100}).top,2000);
});
test('an oversized paragraph starts at its left edge and stays in view',()=>{
 assert.deepEqual(paragraphScrollPosition({bbox:[40,100,560,790]},page,{...view,paperWidth:1200,paperHeight:1600,maxScrollLeft:600,scrollLeft:500,offsetTop:900}),{top:1364,left:76});
});
