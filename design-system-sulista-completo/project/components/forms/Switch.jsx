const React = require('react');
export function Switch({label,checked,defaultChecked,onChange,disabled}){
  const [c,setC]=React.useState(!!defaultChecked);
  const isC = checked!==undefined?checked:c;
  return React.createElement('label',{style:{display:'inline-flex',alignItems:'center',gap:10,cursor:disabled?'not-allowed':'pointer',
      opacity:disabled?0.45:1,fontFamily:'var(--font-body)',fontSize:'var(--text-base)'}},
    React.createElement('span',{role:'switch','aria-checked':isC,tabIndex:0,
      onClick:()=>{if(disabled)return;if(checked===undefined)setC(!isC);onChange&&onChange(!isC);},
      style:{position:'relative',width:40,height:22,borderRadius:'var(--radius-pill)',flexShrink:0,
        background:isC?'var(--brand-accent)':'var(--neutral-300)',transition:'background var(--duration-base) var(--ease-standard)'}},
      React.createElement('span',{style:{position:'absolute',top:3,left:isC?21:3,width:16,height:16,borderRadius:'50%',
        background:'#fff',boxShadow:'var(--shadow-sm)',transition:'left var(--duration-base) var(--ease-standard)'}})),
    label);
}
