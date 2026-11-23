// Only used to rebuild tailwind.css after adding new Tailwind classes to a page (the app itself never runs this):
//   npx tailwindcss@3 -c tailwind.config.js -o tailwind.css --minify
module.exports = {
  content: ['./*.html', '!./dashboard_live.html', './dialog.js', './ui.js'],
  safelist: ['grid-cols-1', 'grid-cols-2', 'grid-cols-3', 'grid-cols-4', 'grid-cols-5'],   // built in JavaScript
  theme: { extend: {} },
};
