// wb-menu.js 1.0 - the Workbench 1.3 menu bar of a rebuild's page (amiga-re-kit 1.0.17; the bar of Alien Breed II and Superfrog
// on arek.fun, first written for Alien Breed / Turrican II - presentation only, no game data). It does not drive the game: an
// open menu or requester calls suspend(), closing it calls restore(); the page's own pause is untouched.
//   const shell = new WbMenu.Shell(document.getElementById('shell'), { suspend: () => { menuPause = true; }, restore: () => { menuPause = false; canvas.focus(); } });
//   shell.openDialog('about-shade'); shell.closeAll(); shell.message('Saved', false); shell.busy   // the game reads no keys while busy
//   WbMenu.editable(e.target)   // a key typed into an input or select is not the game's
// Markup (wb.css): #shell > nav#wbbar > .wbmenu > button.wbtitle#menu-x[aria-expanded] + div.wbpanel[hidden] with .wbitem
// buttons ([data-close-menu] closes the menu); a requester = div.requester-shade[hidden] > section.wbwin.requester with a
// [data-close-dialog] button, inside #shell (the root hears its clicks); #wbnotice (an <output> in #wbstatus) shows message(). Keys: Esc closes, the arrows walk the bar
// and a panel, Home / End, Tab cycles inside a requester.
'use strict';
const WbMenu=(()=>{
    const editable=target=>!!target?.closest?.('input,textarea,select,[contenteditable=""],[contenteditable="true"]');
    class Shell {
        constructor(root,{suspend,restore}){
            this.root=root;this.suspend=suspend;this.restore=restore;this.current=null;this.dialog=null;this.timer=null;
            this.menus=[...root.querySelectorAll('.wbmenu')].map(element=>({element,button:element.querySelector('.wbtitle'),panel:element.querySelector('.wbpanel'),hoverAt:0}));
            for(const m of this.menus){
                m.button.addEventListener('click',()=>{
                    // WebKit on macOS does not focus buttons on mouse clicks.
                    m.button.focus({preventScroll:true});
                    if(this.current===m&&m.hoverAt&&performance.now()-m.hoverAt<500)return;
                    if(this.current===m)this.close();else this.open(m.button.id);
                });
                m.button.addEventListener('pointerenter',()=>{
                    if(this.current&&this.current!==m){this.open(m.button.id);m.hoverAt=performance.now();}
                });
            }
            root.addEventListener('click',e=>{
                if(e.target.closest('[data-close-dialog]'))this.closeDialog();
                else if(e.target.closest('[data-close-menu]'))this.close();
            });
            document.addEventListener('pointerdown',e=>{
                if(this.current&&!e.target.closest('.wbmenu')){
                    this.close();e.preventDefault();e.stopPropagation();
                }
                if(this.dialog&&e.target===this.dialog){this.closeDialog();e.preventDefault();e.stopPropagation();}
            },true);
            document.addEventListener('keydown',e=>this.key(e),true);
            window.addEventListener('resize',()=>this.position());
            document.addEventListener('fullscreenchange',()=>this.position());
        }
        get busy(){return !!(this.current||this.dialog);}
        open(id,focus=false){
            if(this.dialog)return;
            const m=this.menus.find(m=>m.button.id===id);if(!m)return;
            this.close(false);this.current=m;m.panel.hidden=false;m.button.setAttribute('aria-expanded','true');
            this.suspend();this.position();
            if(focus)this.items(m.panel)[0]?.focus();
        }
        close(returnFocus=true){
            if(!this.current)return;
            this.current.panel.hidden=true;this.current.button.setAttribute('aria-expanded','false');this.current.hoverAt=0;this.current=null;
            if(returnFocus&&!this.dialog)this.restore();
        }
        openDialog(id){
            this.close(false);this.dialog=document.getElementById(id);this.dialog.hidden=false;this.suspend();
            const first=this.dialog.querySelector('[data-slot]:not(:disabled)')||this.dialog.querySelector('[data-close-dialog]');first?.focus();
        }
        closeDialog(returnFocus=true){if(!this.dialog)return;this.dialog.hidden=true;this.dialog=null;if(returnFocus)this.restore();}
        closeAll(){const busy=this.busy;this.close(false);this.closeDialog(false);if(busy)this.restore();}
        position(){
            if(!this.current)return;
            const {button,panel}=this.current,b=button.getBoundingClientRect(),width=panel.getBoundingClientRect().width;
            panel.style.left=Math.max(4,Math.min(b.left,window.innerWidth-width-4))+'px';
        }
        items(panel){return [...panel.querySelectorAll('button:not(:disabled),a[href],input:not(:disabled),select:not(:disabled),summary')].filter(e=>e.getClientRects().length);}
        key(e){
            if(e.key==='Escape'&&this.busy){this.closeAll();e.preventDefault();e.stopImmediatePropagation();return;}
            if(this.dialog){
                if(e.key==='Tab'){
                    const items=this.items(this.dialog),i=items.indexOf(document.activeElement);
                    items[(i+(e.shiftKey?-1:1)+items.length)%items.length]?.focus();e.preventDefault();e.stopImmediatePropagation();
                }
                return;
            }
            const m=this.menus.find(m=>m.button===document.activeElement);
            if(m&&['ArrowLeft','ArrowRight','ArrowDown','ArrowUp'].includes(e.key)){
                if(e.key==='ArrowDown'||e.key==='ArrowUp')this.open(m.button.id,true);
                else{const i=this.menus.indexOf(m),next=this.menus[(i+(e.key==='ArrowRight'?1:-1)+this.menus.length)%this.menus.length];
                    next.button.focus();if(this.current)this.open(next.button.id);}
                e.preventDefault();e.stopImmediatePropagation();return;
            }
            if(this.current&&!editable(e.target)&&['ArrowDown','ArrowUp','Home','End'].includes(e.key)){
                const items=this.items(this.current.panel),i=items.indexOf(document.activeElement);
                const index=e.key==='Home'?0:e.key==='End'?items.length-1:(i+(e.key==='ArrowDown'?1:-1)+items.length)%items.length;
                items[index]?.focus();e.preventDefault();e.stopImmediatePropagation();
            }
        }
        message(text,error=false){
            const el=document.getElementById('wbnotice');clearTimeout(this.timer);el.textContent=text;el.hidden=false;
            el.style.color=error?'#a02000':'';this.timer=setTimeout(()=>{el.hidden=true;},error?5000:2500);
        }
    }
    return{Shell,editable};
})();
