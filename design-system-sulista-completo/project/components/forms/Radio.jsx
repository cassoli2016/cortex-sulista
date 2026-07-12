const React = require('react');
export function Radio({label,name,value,checked,defaultChecked,onChange,disabled}){
  return React.createElement('label',{style:{display:'inline-flex',alignItems:'center',gap:10,cursor:disabled?'not-allowed':'pointer',
      opacity:disabled?0.45:1,fontFamily:'var(--font-body)',fontSize:'var(--text-base)'}},
    React.createElement('input',{type:'radio',name,value,checked,defaultChecked,disabled,onChange,
      style:{appearance:'none',width:18,height:18,margin:0,borderRadius:'50%',border:'2px solid var(--border-strong)',
        background:'var(--surface-card)',cursor:'inherit',display:'grid',placeContent:'center',
        transition:'border-color var(--duration-fast) var(--ease-standard)'},
      onInput:e=>{},
      className:'ds-radio'}),
    React.createElement('style',null,'.ds-radio:checked{border-color:var(--brand-accent)!important;background:radial-gradient(circle,var(--brand-accent) 0 5px,var(--surface-card) 5.5px)!important;}'),
    label);
}
