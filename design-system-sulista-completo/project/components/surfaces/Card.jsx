const React = require('react');
export function Card({kicker,title,children,footer,hoverable,padding=20,style}){
  const [h,setH]=React.useState(false);
  return React.createElement('div',{onMouseEnter:()=>setH(true),onMouseLeave:()=>setH(false),
    style:{background:'var(--surface-card)',border:'1px solid var(--border-default)',borderRadius:'var(--radius-lg)',
      boxShadow:hoverable&&h?'var(--shadow-md)':'var(--shadow-sm)',padding,fontFamily:'var(--font-body)',
      transition:'box-shadow var(--duration-base) var(--ease-standard)',...style}},
    kicker&&React.createElement('div',{style:{fontSize:'var(--text-xs)',fontWeight:'var(--weight-semibold)',letterSpacing:'var(--tracking-kicker)',
      textTransform:'uppercase',color:'var(--text-muted)',marginBottom:6}},kicker),
    title&&React.createElement('div',{style:{fontFamily:'var(--font-display)',fontSize:'var(--text-lg)',fontWeight:'var(--weight-bold)',
      color:'var(--text-body)',marginBottom:children?8:0,lineHeight:'var(--leading-snug)'}},title),
    children,
    footer&&React.createElement('div',{style:{marginTop:16,paddingTop:12,borderTop:'1px solid var(--border-default)',
      fontSize:'var(--text-sm)',color:'var(--text-muted)'}},footer));
}
