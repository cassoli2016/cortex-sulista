const React = require('react');
export function Checkbox({label,checked,defaultChecked,onChange,disabled}){
  const [c,setC]=React.useState(!!defaultChecked);
  const isC = checked!==undefined?checked:c;
  return React.createElement('label',{style:{display:'inline-flex',alignItems:'center',gap:10,cursor:disabled?'not-allowed':'pointer',
      opacity:disabled?0.45:1,fontFamily:'var(--font-body)',fontSize:'var(--text-base)'}},
    React.createElement('input',{type:'checkbox',checked:isC,disabled,
      onChange:e=>{if(checked===undefined)setC(e.target.checked);onChange&&onChange(e);},
      style:{appearance:'none',width:18,height:18,margin:0,border:'2px solid '+(isC?'var(--brand-accent)':'var(--border-strong)'),
        borderRadius:'var(--radius-sm)',background:isC?'var(--brand-accent)':'var(--surface-card)',cursor:'inherit',
        backgroundImage:isC?"url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='white' stroke-width='4'%3E%3Cpath d='M5 13l4 4 10-10'/%3E%3C/svg%3E\")":'none',
        backgroundSize:'12px',backgroundPosition:'center',backgroundRepeat:'no-repeat',
        transition:'background var(--duration-fast) var(--ease-standard)'}}),
    label);
}
