const React = require('react');
const S = {
  primary:{bg:'var(--brand-accent)',bgH:'var(--orange-600)',bgA:'var(--orange-700)',fg:'var(--text-on-accent)',bd:'transparent'},
  secondary:{bg:'var(--brand-primary)',bgH:'var(--navy-800)',bgA:'var(--navy-900)',fg:'#fff',bd:'transparent'},
  outline:{bg:'transparent',bgH:'var(--navy-50)',bgA:'var(--navy-100)',fg:'var(--brand-primary)',bd:'var(--border-strong)'},
  ghost:{bg:'transparent',bgH:'var(--neutral-100)',bgA:'var(--neutral-200)',fg:'var(--brand-primary)',bd:'transparent'},
  danger:{bg:'var(--status-danger)',bgH:'var(--red-700)',bgA:'var(--red-700)',fg:'#fff',bd:'transparent'}
};
const SZ = {sm:{h:32,px:12,fs:'var(--text-sm)'},md:{h:40,px:16,fs:'var(--text-base)'},lg:{h:48,px:22,fs:'var(--text-md)'}};
export function Button({variant='primary',size='md',disabled,block,children,style,...rest}){
  const v=S[variant]||S.primary, z=SZ[size]||SZ.md;
  const [st,setSt]=React.useState('idle');
  const bg = st==='active'?v.bgA: st==='hover'?v.bgH: v.bg;
  return React.createElement('button',{disabled,
    onMouseEnter:()=>setSt('hover'),onMouseLeave:()=>setSt('idle'),
    onMouseDown:()=>setSt('active'),onMouseUp:()=>setSt('hover'),
    style:{display:block?'flex':'inline-flex',width:block?'100%':undefined,alignItems:'center',justifyContent:'center',gap:8,
      height:z.h,padding:'0 '+z.px+'px',fontFamily:'var(--font-body)',fontSize:z.fs,fontWeight:'var(--weight-semibold)',
      color:v.fg,background:bg,border:'1px solid '+v.bd,borderRadius:'var(--radius-sm)',cursor:disabled?'not-allowed':'pointer',
      opacity:disabled?0.45:1,transition:'background var(--duration-fast) var(--ease-standard)',...style},...rest},children);
}
