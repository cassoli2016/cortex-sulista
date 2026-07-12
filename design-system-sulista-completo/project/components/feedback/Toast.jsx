const React = require('react');
const T = {success:'var(--status-success)',warning:'var(--status-warning)',danger:'var(--status-danger)',info:'var(--status-info)'};
export function Toast({tone='info',title,children,onClose,style}){
  return React.createElement('div',{role:'status',style:{display:'flex',gap:12,alignItems:'flex-start',width:360,maxWidth:'100%',
    background:'var(--surface-inverse)',color:'var(--text-inverse)',borderLeft:'3px solid '+(T[tone]||T.info),
    borderRadius:'var(--radius-md)',boxShadow:'var(--shadow-lg)',padding:'12px 14px',fontFamily:'var(--font-body)',...style}},
    React.createElement('div',{style:{flex:1}},
      title&&React.createElement('div',{style:{fontSize:'var(--text-sm)',fontWeight:'var(--weight-semibold)'}},title),
      children&&React.createElement('div',{style:{fontSize:'var(--text-sm)',color:'var(--neutral-300)',marginTop:2}},children)),
    onClose&&React.createElement('button',{onClick:onClose,'aria-label':'Fechar',
      style:{border:'none',background:'transparent',color:'var(--neutral-400)',cursor:'pointer',fontSize:14,padding:0}},'\u00d7'));
}
