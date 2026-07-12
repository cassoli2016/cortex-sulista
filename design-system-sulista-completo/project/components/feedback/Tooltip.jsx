const React = require('react');
export function Tooltip({content,side='top',children}){
  const [v,setV]=React.useState(false);
  const pos = side==='bottom'?{top:'calc(100% + 6px)'}:{bottom:'calc(100% + 6px)'};
  return React.createElement('span',{style:{position:'relative',display:'inline-flex'},
    onMouseEnter:()=>setV(true),onMouseLeave:()=>setV(false)},
    children,
    v&&React.createElement('span',{role:'tooltip',style:{position:'absolute',left:'50%',transform:'translateX(-50%)',...pos,
      background:'var(--neutral-900)',color:'#fff',fontFamily:'var(--font-body)',fontSize:'var(--text-xs)',
      padding:'5px 8px',borderRadius:'var(--radius-sm)',whiteSpace:'nowrap',zIndex:50,boxShadow:'var(--shadow-md)'}},content));
}
