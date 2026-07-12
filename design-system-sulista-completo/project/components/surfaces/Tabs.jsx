const React = require('react');
export function Tabs({tabs=[],active,defaultActive=0,onChange,style}){
  const [a,setA]=React.useState(defaultActive);
  const cur = active!==undefined?active:a;
  return React.createElement('div',{role:'tablist',style:{display:'flex',gap:4,borderBottom:'1px solid var(--border-default)',
    fontFamily:'var(--font-body)',...style}},
    tabs.map((t,i)=>React.createElement('button',{key:i,role:'tab','aria-selected':cur===i,
      onClick:()=>{if(active===undefined)setA(i);onChange&&onChange(i);},
      style:{padding:'10px 14px',border:'none',background:'transparent',cursor:'pointer',
        fontSize:'var(--text-base)',fontWeight:cur===i?'var(--weight-semibold)':'var(--weight-regular)',
        color:cur===i?'var(--brand-primary)':'var(--text-muted)',
        boxShadow:cur===i?'inset 0 -2px 0 var(--brand-accent)':'none',
        transition:'color var(--duration-fast) var(--ease-standard)'}},t)));
}
