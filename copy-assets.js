const fs = require('node:fs');
const path = require('node:path');

// Mapeo Origen (node_modules) -> Destino (src/static/vendor)
const assets = [
    { src: 'bootstrap/dist', dest: 'bootstrap' },
    { src: '@fortawesome/fontawesome-free/css', dest: 'font-awesome/css' },
    { src: '@fortawesome/fontawesome-free/webfonts', dest: 'font-awesome/webfonts' },
    { src: 'chart.js/dist/chart.umd.js', dest: 'chart.js/chart.js' },
    { src: 'easymde/dist', dest: 'easymde' },
    { src: 'simple-calendar-js/dist', dest: 'simple-calendar-js' },
    { src: 'simple-datatables/dist', dest: 'simple-datatables' },
    { src: 'sortablejs/Sortable.min.js', dest: 'sortablejs/Sortable.min.js' },
    { src: 'tom-select/dist', dest: 'tom-select' },
    { src: 'mermaid/dist/mermaid.min.js', dest: 'mermaid/mermaid.min.js' },
    // SunEditor WYSIWYG (MIT license)
    { src: 'suneditor/dist', dest: 'suneditor' },
    // Swagger UI
    { src: 'swagger-ui-dist', dest: 'swagger-ui' },
    // OrgChart.js (vanilla JS org chart by dabeng)
    { src: 'orgchart.js/src', dest: 'orgchart.js' },
    // html2canvas (for OrgChart PNG export)
    { src: 'html2canvas/dist/html2canvas.min.js', dest: 'html2canvas/html2canvas.min.js' }
];



const targetBase = path.join(__dirname, 'src/static/vendor');

// Crear directorio base si no existe
if (!fs.existsSync(targetBase)) {
    fs.mkdirSync(targetBase, { recursive: true });
}

console.log('📦 Copying frontend assets from node_modules...\n');

assets.forEach(asset => {
    const srcPath = path.join(__dirname, 'node_modules', asset.src);
    const destPath = path.join(targetBase, asset.dest);

    // Asegurar que el directorio destino existe
    const destDir = path.dirname(destPath);
    if (!fs.existsSync(destDir)) {
        fs.mkdirSync(destDir, { recursive: true });
    }

    try {
        // Copia recursiva si es directorio, o archivo simple
        fs.cpSync(srcPath, destPath, { recursive: true, force: true });
        console.log(`✅ Copied ${asset.src} -> ${asset.dest}`);
    } catch (err) {
        console.error(`❌ Error copying ${asset.src}:`, err.message);
        process.exit(1);
    }
});

console.log('\n✅ All assets copied successfully!');
