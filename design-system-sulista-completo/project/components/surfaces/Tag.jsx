const React = require('react');
export function Tag({accent,onRemove,children,style}){
  return React.createElement('span',{style:{display:'inline-flex',alignItems:'center',gap:6,height:24,padding:'0 10px',
    borderRadius:'var(--radius-sm)',border:'1px solid '+(accent?'var(--orange-200)':'var(--border-default)'),
    background:accent?'var(--orange-50)':'var(--surface-card)',color:accent?'var(--orange-700)':'var(--neutral-700)',
    fontFamily:'var(--font-body)',fontSize:'var(--text-xs)',fontWeight:'var(--weight-medium)',...style}},
    children,
    onRemove&&React.createElement('button',{onClick:onRemove,'aria-label':'Remover',
      style:{border:'none',background:'transparent',cursor:'pointer',color:'inherit',padding:0,fontSize:12,lineHeight:1}},'\u00d7'));
}
