const AVATAR_SVG = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40">
  <defs><clipPath id="a"><circle cx="20" cy="20" r="20"/></clipPath></defs>
  <circle cx="20" cy="20" r="20" fill="#6D42C5"/>
  <g clip-path="url(#a)" fill="#FFFFFF">
    <circle cx="20" cy="16" r="7"/>
    <ellipse cx="20" cy="39.5" rx="18" ry="12.5"/>
  </g>
</svg>`;

export const DEFAULT_AVATAR = `data:image/svg+xml,${encodeURIComponent(
  AVATAR_SVG,
)}`;
