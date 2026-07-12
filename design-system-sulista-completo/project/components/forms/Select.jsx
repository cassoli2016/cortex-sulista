const React = require('react');
export function Select({label,options=[],hint,error,style,...rest}){
  return React.createElement('label',{style:{display:'flex',flexDirection:'column',gap:6,fontFamily:'var(--font-body)',...style}},
    label&&React.createElement('span',{style:{fontSize:'var(--text-sm)',fontWeight:'var(--weight-medium)'}},label),
    React.createElement('select',{style:{height:40,padding:'0 12px',background:'var(--surface-card)',
      border:'1px solid '+(error?'var(--status-danger)':'var(--border-default)'),borderRadius:'var(--radius-sm)',
      fontSize:'var(--text-base)',fontFamily:'var(--font-body)',color:'var(--text-body)',cursor:'pointer'},...rest},
      options.map((o,i)=>React.createElement('option',{key:i,value:typeof o==='string'?o:o.value},typeof o==='string'?o:o.label))),
    (error||hint)&&React.createElement('span',{style:{fontSize:'var(--text-xs)',color:error?'var(--status-danger)':'var(--text-muted)'}},error||hint));
}
