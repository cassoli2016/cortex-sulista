(function(){
  var cur = document.currentScript.src;
  var ROOT = cur.slice(0, cur.lastIndexOf('/')+1);
  var MODS = [
    'components/forms/Button.jsx','components/forms/IconButton.jsx','components/forms/Input.jsx',
    'components/forms/Select.jsx','components/forms/Checkbox.jsx','components/forms/Radio.jsx',
    'components/forms/Switch.jsx','components/surfaces/Card.jsx','components/surfaces/Badge.jsx',
    'components/surfaces/Tag.jsx','components/surfaces/Tabs.jsx','components/feedback/Dialog.jsx',
    'components/feedback/Toast.jsx','components/feedback/Tooltip.jsx'];
  window.__dsReady = new Promise(function(resolve){
    var s = document.createElement('script');
    s.src = ROOT + '_ds_bundle.js';
    s.onload = function(){
      var names = Object.getOwnPropertyNames(window);
      for (var i=0;i<names.length;i++){ var v; try{ v = window[names[i]]; }catch(e){ continue; }
        if (v && typeof v==='object' && v!==window && typeof v.Button==='function' && typeof v.Toast==='function'){ resolve(v); return; } }
      fallback(resolve);
    };
    s.onerror = function(){ fallback(resolve); };
    document.head.appendChild(s);
  });
  function fallback(resolve){
    var cache = {};
    function norm(path){ var parts=path.split('/'), out=[]; for (var i=0;i<parts.length;i++){ var p=parts[i];
      if(p==='.'||p==='') continue; if(p==='..') out.pop(); else out.push(p); } return out.join('/'); }
    Promise.all(MODS.map(function(m){ return fetch(ROOT+m).then(function(r){return r.text();}).then(function(src){ return {path:m, src:src}; }); }))
    .then(function(list){
      var srcs={}; list.forEach(function(e){ srcs[e.path]=e.src; });
      function req(from, spec){
        if (spec==='react') return window.React;
        var dir = from.split('/').slice(0,-1).join('/');
        var p = norm(dir+'/'+spec);
        if (cache[p]) return cache[p].exports;
        // Components are plain JS (React.createElement) — only `export function` needs converting.
        var names = [];
        var code = srcs[p].replace(/export function (\w+)/g, function(_, n){ names.push(n); return 'function ' + n; });
        code += names.map(function(n){ return ';module.exports.' + n + ' = ' + n + ';'; }).join('');
        var module = {exports:{}};
        cache[p] = module;
        new Function('require','module','exports', code)(function(s){ return req(p,s); }, module, module.exports);
        return module.exports;
      }
      var NS = {};
      MODS.forEach(function(m){ Object.assign(NS, req('', m)); });
      window.Austral = NS;
      resolve(NS);
    });
  }
})();
