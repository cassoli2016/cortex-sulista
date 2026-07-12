const React = require('react');
export function Input({label,hint,error,prefix,mono,style,inputStyle,...rest}){
  const [f,setF]=React.useState(false);
  return React.createElement('label',{style:{display:'flex',flexDirection:'column',gap:6,fontFamily:'var(--font-body)',...style}},
    label&&React.createElement('span',{style:{fontSize:'var(--text-sm)',fontWeight:'var(--weight-medium)',color:'var(--text-body)'}},label),
    React.createElement('span',{style:{display:'flex',alignItems:'center',gap:8,height:40,padding:'0 12px',background:'var(--surface-card)',
      border:'1px solid '+(error?'var(--status-danger)':f?'var(--brand-primary)':'var(--border-default)'),
      borderRadius:'var(--radius-sm)',transition:'border-color var(--duration-fast) var(--ease-standard)'}},
      prefix&&React.createElement('span',{style:{color:'var(--text-muted)',fontSize:'var(--text-sm)'}},prefix),
      React.createElement('input',{onFocus:()=>setF(true),onBlur:()=>setF(false),
        style:{flex:1,border:'none',outline:'none',background:'transparent',fontSize:'var(--text-base)',color:'var(--text-body)',
          fontFamily:mono?'var(--font-mono)':'var(--font-body)',minWidth:0,...inputStyle},...rest})),
    (error||hint)&&React.createElement('span',{style:{fontSize:'var(--text-xs)',color:error?'var(--status-danger)':'var(--text-muted)'}},error||hint));
}
