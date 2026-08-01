const http = require('http');
http.get('http://localhost:3000', (res) => {
  let d = '';
  res.on('data', c => d += c);
  res.on('end', () => {
    const m = d.match(/<body[^>]*>([\s\S]*?)<\/body>/);
    if (m) {
      let body = m[1];
      body = body.replace(/<script[\s\S]*?<\/script>/g, '');
      body = body.replace(/<!--[\s\S]*?-->/g, '');
      console.log('Body after cleanup:', body.substring(0, 500));
      console.log('Has Dashboard:', body.includes('仪表盘'));
    }
  });
});
