import Image from 'next/image';

const iconMap = {
    'API Tool': '/toolIcons/tool_api_tool.svg',
    'Brave Search Tool': '/toolIcons/tool_brave.svg',
    'Cryptoprice Tool': '/toolIcons/tool_cryptoprice.svg',
    'Ntfy Tool': '/toolIcons/tool_ntfy.svg',
    'PostgreSQL Tool': '/toolIcons/tool_postgres.svg',
    'Read Webpage Tool': '/toolIcons/tool_read_webpage.svg',
    'Telegram Tool': '/toolIcons/tool_telegram.svg'
};


export function ToolCards({ items }) {
    return (
        <>
            <div className="tool-cards">
                {items.map(({ title, link, description }) => {
                    const isExternal = link.startsWith('https://');
                    const iconSrc = iconMap[title] || '/default-icon.png'; // Default icon if not found

                    return (
                        <div
                            key={title}
                            className={`card${isExternal ? ' external' : ''}`}
                        >
                            <a href={link} target={isExternal ? '_blank' : undefined} rel="noopener noreferrer" className="card-link-wrapper">
                                <div className="card-icon-container">
                                    {iconSrc && <div className="card-icon"><Image src={iconSrc} alt={title} width={32} height={32} /></div>} {/* Reduced icon size */}
                                </div>
                                <h3 className="card-title">{title}</h3>
                                {description && <p className="card-description">{description}</p>}
                                {/* Card URL element removed from here */}
                            </a>
                        </div>
                    );
                })}
            </div>

            <style jsx>{`
               .tool-cards {
                    margin-top: 24px;
                    display: grid;
                    grid-template-columns: 1fr;
                    gap: 16px;
                }
                @media (min-width: 768px) {
                    .tool-cards {
                        grid-template-columns: 1fr 1fr; /* Keeps two columns on wider screens */
                    }
                }
                .card {
                    background-color: #222222;
                    border-radius: 8px;
                    padding: 16px; /* Existing padding */
                    transition: background-color 0.3s;
                    position: relative;
                    color: #ffffff;
                    display: flex; /* Using flex to help with alignment */
                    flex-direction: column;
                    /* align-items: center; // Alignment for items inside card-link-wrapper is better */
                    /* justify-content: center; // We want content to flow from top */
                    height: 100%; /* Fill the height of the grid cell, ensures cards in a row are same height */
                }
                .card:hover {
                    background-color: #333333;
                }
                .card.external::after {
                    content: "↗";
                    position: absolute;
                    top: 12px;
                    right: 12px;
                    color: #ffffff;
                    font-size: 0.7em;
                    opacity: 0.8;
                }
                .card-link-wrapper {
                    display: flex;
                    flex-direction: column;
                    align-items:center; /* Centers icon, title, description horizontally */
                    text-align: center; /* Ensures text within p and h3 is centered */
                    color: inherit;
                    text-decoration: none;
                    width:100%;
                    height: 100%; /* Make the link wrapper take full card height */
                    justify-content: flex-start; /* Align content to the top */
                }
               .card-icon-container{
                    display:flex;
                    justify-content:center;
                    width: 100%;
                    margin-top: 8px; /* Added some margin at the top if needed */
                    margin-bottom: 12px; /* Increased space between icon and title */
               }
                .card-icon {
                   display: block;
                   /* margin: 0 auto; // Center handled by card-icon-container */
                }
                .card-title {
                    font-weight: 600;
                    margin-bottom: 8px; /* Increased space below title */
                    font-size: 16px; /* Consider increasing slightly if descriptions are longer e.g. 17px or 18px */
                    color: #f0f0f0;
                }
                .card-description {
                    /* margin-bottom: 0; // Original value */
                    font-size: 14px; /* Slightly increased font size for better readability */
                    color: #aaaaaa;
                    line-height: 1.5; /* Slightly increased line height */
                    flex-grow: 1; /* Allows description to take available space */
                    overflow-y: auto; /* Adds scroll if description is too long, though ideally content fits */
                    padding-bottom: 8px; /* Add some padding at the bottom of the description area */
                }
            `}</style>
        </>
    );
}