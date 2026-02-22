# Odoo CRM Customization Project

This repository contains customizations and extensions for Odoo CRM functionality.

## Project Structure

```
odooCRM/
├── custom_modules/           # Custom Odoo modules
│   └── crm_custom/          # Main CRM customization module
├── docker/                  # Docker configuration files
├── requirements/            # Python requirements
├── .gitignore              # Git ignore rules
└── README.md               # This file
```

## Prerequisites

- Python 3.8 or higher
- PostgreSQL 12 or higher
- Odoo 16.0
- Git

## Development Environment Setup

1. Create and activate Python virtual environment:
```bash
python -m venv venv
.\venv\Scripts\activate  # Windows
```

2. Install requirements:
```bash
pip install -r requirements/requirements.txt
```

3. Configure PostgreSQL:
- Create a database user
- Create a database for development

4. Configure Odoo:
- Copy the odoo.conf.example to odoo.conf
- Update database connection settings
- Set development mode

## Running the Development Server

1. Start PostgreSQL service
2. Run Odoo server:
```bash
python odoo-bin -c odoo.conf
```

3. Access the instance at http://localhost:8069

## Development Guidelines

1. Module Structure
- Follow Odoo module naming conventions
- Maintain proper directory structure
- Document all customizations

2. Code Style
- Follow PEP 8 guidelines
- Use meaningful variable names
- Add docstrings to functions and classes

3. Testing
- Write unit tests for new functionality
- Test database migrations
- Verify UI changes

## Common Debugging Procedures

1. Check logs in:
- Odoo server logs
- PostgreSQL logs
- Browser console

2. Development Tools:
- Developer mode in Odoo
- Technical features
- Debug mode in Python

## Contributing

1. Create feature branches
2. Follow coding standards
3. Write tests
4. Submit pull requests

## License

[Your License Here] 