// Draws the three income charts. Colours come from the CSS variables so they follow the theme.
const data = JSON.parse(document.getElementById('chart-data').textContent);
let charts = [];
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();

function draw() {
  charts.forEach(c => c.destroy());
  charts = [];
  const up = css('--up'), down = css('--down'), line = css('--line');
  Chart.defaults.color = css('--mute');
  Chart.defaults.font.family = '"Hanken Grotesk", system-ui, sans-serif';
  [['c-month', data.monthly], ['c-year', data.yearly], ['c-day', data.daily]].forEach(([id, d]) => {
    charts.push(new Chart(document.getElementById(id), {
      type: 'bar',
      data: { labels: d.labels, datasets: [{ label: 'Income (' + data.currency + ')', data: d.values,
        backgroundColor: d.values.map(v => (v < 0 ? down : up)) }] },
      options: { maintainAspectRatio: false, plugins: { legend: { display: false } },
        scales: { x: { grid: { color: line } }, y: { grid: { color: line } } } },
    }));
  });
}
draw();
document.getElementById('theme').addEventListener('change', () => setTimeout(draw, 0));
matchMedia('(prefers-color-scheme: dark)').addEventListener('change', draw);
