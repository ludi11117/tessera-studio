'use strict';
// Legacy UI glyphs use the same locally bundled Lucide set. User prose is untouched.
(() => {
  const names={'＋':'plus','✦':'pencil-line','⚙':'settings','☰':'menu','ⓘ':'info','✕':'x','×':'x','▤':'file-text','▣':'lock-keyhole','▢':'lock-keyhole-open','↗':'arrow-up-right','↶':'undo-2','↓':'arrow-down','↑':'arrow-up','→':'arrow-right','✓':'check'};
  const pattern=/[＋✦⚙☰ⓘ✕×▤▣▢↗↶↓↑→✓]/g;let scheduled=false;
  function render(){
    scheduled=false;if(!window.lucide)return;const nodes=[];
    for(const element of document.querySelectorAll('button,a,.attach-button,.document-icon,.provider-icon')){
      if(element.closest('.markdown,.message-body,.draft-content'))continue;
      const walker=document.createTreeWalker(element,NodeFilter.SHOW_TEXT);
      while(walker.nextNode()){const node=walker.currentNode;if(node.parentElement.closest('svg,textarea,pre,code'))continue;pattern.lastIndex=0;if(pattern.test(node.textContent))nodes.push(node);}
    }
    for(const node of new Set(nodes)){
      if(!node.isConnected)continue;const fragment=document.createDocumentFragment();let previous=0;pattern.lastIndex=0;
      for(const match of node.textContent.matchAll(pattern)){fragment.append(node.textContent.slice(previous,match.index));const icon=document.createElement('i');icon.dataset.lucide=names[match[0]];icon.setAttribute('aria-hidden','true');fragment.append(icon);previous=match.index+1;}
      fragment.append(node.textContent.slice(previous));node.replaceWith(fragment);
    }
    if(document.querySelector('[data-lucide]:not(svg)'))lucide.createIcons({attrs:{'stroke-width':1.6,'aria-hidden':'true'}});
  }
  const observer=new MutationObserver(()=>{if(!scheduled){scheduled=true;requestAnimationFrame(render);}});
  render();observer.observe(document.body,{subtree:true,childList:true});
})();
