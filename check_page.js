const http = require('http');
http.get('http://localhost:3000', (res) => {
  let d = '';
  res.on('data', c => d += c);
  res.on('end', () => {
    // Find the hidden div content
    const idx1 = d.indexOf('<div hidden="">');
    if (idx1 >= 0) {
      const after = d.substring(idx1 + 17);
      const idx2 = after.indexOf('</div>');
      console.log('hidden div content:', after.substring(0, 500));
    } else {
      console.log('no hidden div found');
    }
    // Check if body contains actual React content
    const bodyIdx = d.indexOf('<body');
    const bodyEnd = d.indexOf('</body>');
    const bodyContent = d.substring(bodyIdx, bodyEnd);
    console.log('Body contains AppShell:', bodyContent.includes('AppShell'));
    console.log('Body contains Dashboard:', bodyContent.includes('Dashboard') || bodyContent.includes('仪表盘'));
    console.log('Total body length:', bodyContent.length);
    // Check for hydration markers
    console.log('Has __next_f:', d.includes('__next_f'));
    console.log('Has $L25 (layout-router):', bodyContent.includes('$L25'));
  });
});
