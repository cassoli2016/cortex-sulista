const React = require('react');
const {Button} = require('../forms/Button.jsx');
export function Dialog({open=true,title,children,confirmLabel='Confirmar',cancelLabel='Cancelar',onConfirm,onCancel,danger,width=440}){
  if(!open) return null;
  return React.createElement('div',{style:{position:'absolute',inset:0,background:'rgba(11,25,38,.5)',
    display:'flex',alignItems:'center',justifyContent:'center',padding:24,zIndex:100}},
    React.createElement('div',{role:'dialog','aria-modal':true,style:{width,maxWidth:'100%',background:'var(--surface-card)',
      borderRadius:'var(--radius-lg)',boxShadow:'var(--shadow-lg)',padding:24,fontFamily:'var(--font-body)'}},
      React.createElement('div',{style:{fontFamily:'var(--font-display)',fontSize:'var(--text-lg)',fontWeight:'var(--weight-bold)',
        color:'var(--text-body)',marginBottom:8}},title),
      React.createElement('div',{style:{fontSize:'var(--text-base)',color:'var(--neutral-600)',marginBottom:20}},children),
      React.createElement('div',{style:{display:'flex',justifyContent:'flex-end',gap:8}},
        React.createElement(Button,{variant:'ghost',onClick:onCancel},cancelLabel),
        React.createElement(Button,{variant:danger?'danger':'primary',onClick:onConfirm},confirmLabel))));
}
