import Image from 'next/image';

const iconMap = {
    'Amazon Lightsail': '/lightsail.png',
    'Railway': '/railway.png',
    'Civo Compute Cloud': '/civo.png',
    'DigitalOcean Droplet': '/digitalocean.png',
    'Kamatera Cloud': '/kamatera.png',
};


export function DeploymentCards({ items }) {
    return (
        <>
            <div className="deployment-cards">
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
                                <p className="card-url">{new URL(link).hostname.replace('www.', '')}</p>
                            </a>
                        </div>
                    );
                })}
            </div>

            <style jsx>{`
               .deployment-cards {
                    margin-top: 24px;
                    display: grid;
                    grid-template-columns: 1fr;
                    gap: 16px;
                }
                @media (min-width: 768px) {
                    .deployment-cards {
                        grid-template-columns: 1fr 1fr;
                    }
                }
                .card {
                    background-color: #222222;
                    border-radius: 8px;
                    padding: 16px;
                    transition: background-color 0.3s;
                    position: relative;
                    color: #ffffff;
                    /* Make the card a flex container */
                    display: flex;
                    flex-direction: column;
                    align-items: center; /* Center horizontally */
                    justify-content: center; /* Center vertically */
                    height: 100%; /* Fill the height of the grid cell */
                  
                }
                .card:hover {
                    background-color: #333333;
                }
                .card.external::after {
                    content: "↗";
                    position: absolute;
                    top: 12px; /* Adjusted position */
                    right: 12px; /* Adjusted position */
                    color: #ffffff;
                    font-size: 0.7em; /* Reduced size */
                    opacity: 0.8; /* Slightly faded */
                }
                .card-link-wrapper {
                    display: flex;
                    flex-direction: column;
                    align-items:center;
                    color: inherit;
                    text-decoration: none;
                    width:100%; /* Important: make link wrapper take full width */
                }
               .card-icon-container{
                display:flex;
                justify-content:center;
                 width: 100%;
                 margin-bottom: 8px; /* Space between icon and title */
               }
                .card-icon {
                   display: block;
                   margin: 0 auto;

                }
                .card-title {
                    font-weight: 600;
                    margin-bottom: 4px;
                    font-size: 16px;
                    text-align: center;
                    color: #f0f0f0; /* Lighter title color if needed */
                }
                .card-description {
                    margin-bottom: 0;
                    font-size: 13px;
                    color: #aaaaaa;
                    text-align: center;
                    line-height: 1.4;
                }
                .card-url {
                    margin-top: 8px; /*Keep space consistent */
                    font-size: 11px;
                    color: #777777;
                    text-align: center;
                    font-family: monospace;
                }
            `}</style>
        </>
    );
}