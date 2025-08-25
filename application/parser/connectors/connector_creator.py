from application.parser.connectors.google_drive.loader import GoogleDriveLoader


class ConnectorCreator:
    """
    Factory class for creating external knowledge base connectors.
    
    These are different from remote loaders as they typically require
    authentication and connect to external document storage systems.
    """
    
    connectors = {
        "google_drive": GoogleDriveLoader,
    }

    @classmethod
    def create_connector(cls, connector_type, *args, **kwargs):
        """
        Create a connector instance for the specified type.
        
        Args:
            connector_type: Type of connector to create (e.g., 'google_drive')
            *args, **kwargs: Arguments to pass to the connector constructor
            
        Returns:
            Connector instance
            
        Raises:
            ValueError: If connector type is not supported
        """
        connector_class = cls.connectors.get(connector_type.lower())
        if not connector_class:
            raise ValueError(f"No connector class found for type {connector_type}")
        return connector_class(*args, **kwargs)

    @classmethod
    def get_supported_connectors(cls):
        """
        Get list of supported connector types.
        
        Returns:
            List of supported connector type strings
        """
        return list(cls.connectors.keys())

    @classmethod
    def is_supported(cls, connector_type):
        """
        Check if a connector type is supported.
        
        Args:
            connector_type: Type of connector to check
            
        Returns:
            True if supported, False otherwise
        """
        return connector_type.lower() in cls.connectors
