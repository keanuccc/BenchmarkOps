const http = require('http');
http.get('http://localhost:3000', (res) => {
  let d = '';
  res.on('data', c => d += c);
  res.on('end', () => {
    // Extract the __next_f data to understand hydration state
    const match = d.match(/self\.__next_f\.push\(\[1,?"([^"]*)"(\}\])/s);
    if (match) {
      console.log('First push payload length:', match[1].length);
    }
    // Look for any error markers in the hydration data
    const hasError = d.includes('"error"') || d.includes('"Exception"') || d.includes('TypeError');
    console.log('Has error markers:', hasError);

    // Check if page component is being rendered
    const pageChunk = d.match(/src_app_page_tsx[^"]*\.js/);
    console.log('Page chunk:', pageChunk ? pageChunk[0] : 'not found');

    // Count script tags
    const scripts = (d.match(/<script/g) || []).length;
    console.log('Script count:', scripts);

    // Check for notFound pattern
    const hasNotFound = d.includes('not-found') || d.includes('404');
    console.log('Has notFound:', hasNotFound);

    // Print the actual rendered body text (what Next.js sends as initial HTML)
    const bodyMatch = d.match(/<body[^>]*>([\s\S]*?)<\/body>/);
    if (bodyMatch) {
      const bodyContent = bodyMatch[1];
      // Remove script tags
      const cleanBody = bodyContent.replace(/<script[\s\S]*?<\/script>/g, '').replace(/<!--[\s\S]*?-->/g, '');
      console.log('Clean body content length:', cleanBody.length);
      console.log('Clean body first 500 chars:', cleanBody.substring(0, 500));
    }
  });
});
