const React = require('react');
export function IconButton({label,variant='ghost',size='md',disabled,children,style,...rest}){
  const dim = size==='sm'?28: size==='lg'?44:36;
  const v = variant==='primary'?{bg:'var(--brand-accent)',fg:'#fff',bgH:'var(--orange-600)'}
    : variant==='outline'?{bg:'transparent',fg:'var(--brand-primary)',bgH:'var(--navy-50)',bd:'var(--border-strong)'}
    : {bg:'transparent',fg:'var(--neutral-600)',bgH:'var(--neutral-100)'};
  const [h,setH]=React.useState(false);
  return React.createElement('button',{'aria-label':label,title:label,disabled,
    onMouseEnter:()=>setH(true),onMouseLeave:()=>setH(false),
    style:{display:'inline-flex',alignItems:'center',justifyContent:'center',width:dim,height:dim,
      background:h&&!disabled?v.bgH:v.bg,color:v.fg,border:'1px solid '+(v.bd||'transparent'),
      borderRadius:'var(--radius-sm)',cursor:disabled?'not-allowed':'pointer',opacity:disabled?0.45:1,
      transition:'background var(--duration-fast) var(--ease-standard)',...style},...rest},children);
}
