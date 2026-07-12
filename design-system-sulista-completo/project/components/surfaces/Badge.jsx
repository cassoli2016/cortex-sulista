const React = require('react');
const T = {
  success:{bg:'var(--green-100)',fg:'var(--green-700)',dot:'var(--green-500)'},
  warning:{bg:'var(--yellow-100)',fg:'var(--yellow-700)',dot:'var(--yellow-500)'},
  danger:{bg:'var(--red-100)',fg:'var(--red-700)',dot:'var(--red-500)'},
  info:{bg:'var(--navy-100)',fg:'var(--navy-700)',dot:'var(--navy-500)'},
  neutral:{bg:'var(--neutral-100)',fg:'var(--neutral-700)',dot:'var(--neutral-400)'}
};
export function Badge({tone='neutral',dot=true,children,style}){
  const t=T[tone]||T.neutral;
  return React.createElement('span',{style:{display:'inline-flex',alignItems:'center',gap:6,height:22,padding:'0 10px',
    borderRadius:'var(--radius-pill)',background:t.bg,color:t.fg,fontFamily:'var(--font-body)',
    fontSize:'var(--text-xs)',fontWeight:'var(--weight-semibold)',...style}},
    dot&&React.createElement('span',{style:{width:6,height:6,borderRadius:'50%',background:t.dot}}),children);
}
