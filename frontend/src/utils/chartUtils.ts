import { Chart as ChartJS } from 'chart.js';

const getOrCreateLegendList = (
  chart: ChartJS,
  id: string,
): HTMLUListElement => {
  const legendContainer = document.getElementById(id);
  let listContainer = legendContainer?.querySelector('ul') as HTMLUListElement;

  if (!listContainer) {
    listContainer = document.createElement('ul');
    listContainer.style.display = 'flex';
    listContainer.style.flexDirection = 'row';
    listContainer.style.margin = '0';
    listContainer.style.padding = '0';

    legendContainer?.appendChild(listContainer);
  }

  return listContainer;
};

export const htmlLegendPlugin = {
  id: 'htmlLegend',
  afterUpdate(chart: ChartJS, args: any, options: { containerID: string }) {
    const ul = getOrCreateLegendList(chart, options.containerID);

    while (ul.firstChild) {
      ul.firstChild.remove();
    }

    const items =
      chart.options.plugins?.legend?.labels?.generateLabels?.(chart) || [];

    items.forEach((item: any) => {
      const li = document.createElement('li');
      li.style.alignItems = 'center';
      li.style.cursor = 'pointer';
      li.style.display = 'flex';
      li.style.flexDirection = 'row';
      li.style.marginLeft = '10px';

      li.onclick = () => {
        chart.setDatasetVisibility(
          item.datasetIndex,
          !chart.isDatasetVisible(item.datasetIndex),
        );
        chart.update();
      };

      const boxSpan = document.createElement('span');
      boxSpan.style.background = item.fillStyle;
      boxSpan.style.borderColor = item.strokeStyle;
      boxSpan.style.borderWidth = item.lineWidth + 'px';
      boxSpan.style.display = 'inline-block';
      boxSpan.style.flexShrink = '0';
      boxSpan.style.height = '10px';
      boxSpan.style.marginRight = '10px';
      boxSpan.style.width = '10px';
      boxSpan.style.borderRadius = '10px';

      const textContainer = document.createElement('p');
      textContainer.style.fontSize = '12px';
      textContainer.style.color = item.fontColor;
      textContainer.style.margin = '0';
      textContainer.style.padding = '0';
      textContainer.style.textDecoration = item.hidden ? 'line-through' : '';

      const text = document.createTextNode(item.text);
      textContainer.appendChild(text);

      li.appendChild(boxSpan);
      li.appendChild(textContainer);
      ul.appendChild(li);
    });
  },
};
