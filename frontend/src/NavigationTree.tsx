import React from 'react';

const NavigationTree = ({ data }) => {
  const renderLinks = (links) => (
    <ul>
      {links.map((link, i) => (
        <li key={i}>
          <a href={link.url}>{link.text}</a>
          {link.sub_links && renderLinks(link.sub_links)}
        </li>
      ))}
    </ul>
  );

  return (
    <div>
      {data.map((item, index) => (
        <div key={index}>
          <h2>{item.title}</h2>
          {renderLinks(item.navigation_links)}
        </div>
      ))}
    </div>
  );
};

export default NavigationTree;
