# En src/seed_prod.py

from src.extensions import db
from src.models import Framework, FrameworkControl

# --- Definiciones de Controles y Prácticas ---

iso_27001_controls = [
    # A.5 Controles Organizacionales (37)
    ("A.5.1", "Políticas para la seguridad de la información"),
    ("A.5.2", "Roles y responsabilidades en seguridad de la información"),
    ("A.5.3", "Segregación de funciones"),
    ("A.5.4", "Responsabilidades de la dirección"),
    ("A.5.5", "Contacto con las autoridades"),
    ("A.5.6", "Contacto con grupos de interés especiales"),
    ("A.5.7", "Inteligencia de amenazas"),
    ("A.5.8", "Seguridad de la información en la gestión de proyectos"),
    ("A.5.9", "Inventario de información y otros activos asociados"),
    ("A.5.10", "Uso aceptable de la información y otros activos asociados"),
    ("A.5.11", "Devolución de activos"),
    ("A.5.12", "Clasificación de la información"),
    ("A.5.13", "Etiquetado de la información"),
    ("A.5.14", "Transferencia de información"),
    ("A.5.15", "Control de acceso"),
    ("A.5.16", "Gestión de identidades"),
    ("A.5.17", "Información de autenticación"),
    ("A.5.18", "Derechos de acceso"),
    ("A.5.19", "Seguridad de la información en las relaciones con proveedores"),
    ("A.5.20", "Gestión de la seguridad en los acuerdos con proveedores"),
    ("A.5.21", "Gestión de la seguridad de la información en la cadena de suministro TIC"),
    ("A.5.22", "Monitorización, revisión y gestión de cambios en servicios de proveedores"),
    ("A.5.23", "Seguridad de la información para el uso de servicios en la nube"),
    ("A.5.24", "Planificación y preparación de la gestión de incidentes de seguridad"),
    ("A.5.25", "Evaluación y decisión sobre eventos de seguridad de la información"),
    ("A.5.26", "Respuesta a incidentes de seguridad de la información"),
    ("A.5.27", "Aprendizaje de los incidentes de seguridad de la información"),
    ("A.5.28", "Recopilación de evidencias"),
    ("A.5.29", "Seguridad de la información durante interrupciones"),
    ("A.5.30", "Disponibilidad de las TIC para la continuidad del negocio"),
    ("A.5.31", "Requisitos legales, estatutarios, regulatorios y contractuales"),
    ("A.5.32", "Derechos de propiedad intelectual"),
    ("A.5.33", "Protección de registros"),
    ("A.5.34", "Privacidad y protección de la Información de Identificación Personal (PII)"),
    ("A.5.35", "Revisión independiente de la seguridad de la información"),
    ("A.5.36", "Cumplimiento de políticas, reglas y estándares de seguridad"),
    ("A.5.37", "Procedimientos operativos documentados"),
    
    # A.6 Controles de Personas (8)
    ("A.6.1", "Selección (Screening)"),
    ("A.6.2", "Términos y condiciones de empleo"),
    ("A.6.3", "Concienciación, educación y formación en seguridad de la información"),
    ("A.6.4", "Proceso disciplinario"),
    ("A.6.5", "Responsabilidades tras la finalización o cambio de empleo"),
    ("A.6.6", "Acuerdos de confidencialidad o no divulgación"),
    ("A.6.7", "Trabajo remoto"),
    ("A.6.8", "Reporte de eventos de seguridad de la información"),
    
    # A.7 Controles Físicos (14)
    ("A.7.1", "Perímetros de seguridad física"),
    ("A.7.2", "Controles de entrada física"),
    ("A.7.3", "Seguridad de oficinas, despachos y recursos"),
    ("A.7.4", "Monitorización de la seguridad física"),
    ("A.7.5", "Protección contra amenazas físicas y ambientales"),
    ("A.7.6", "Trabajo en áreas seguras"),
    ("A.7.7", "Escritorio limpio y pantalla limpia"),
    ("A.7.8", "Ubicación y protección de equipos"),
    ("A.7.9", "Seguridad de los activos fuera de las instalaciones"),
    ("A.7.10", "Medios de almacenamiento"),
    ("A.7.11", "Servicios de suministro (Utilities)"),
    ("A.7.12", "Seguridad del cableado"),
    ("A.7.13", "Mantenimiento de equipos"),
    ("A.7.14", "Eliminación segura o reutilización de equipos"),
    
    # A.8 Controles Tecnológicos (34)
    ("A.8.1", "Dispositivos de usuario final (Endpoint devices)"),
    ("A.8.2", "Derechos de acceso privilegiado"),
    ("A.8.3", "Restricción de acceso a la información"),
    ("A.8.4", "Acceso al código fuente"),
    ("A.8.5", "Autenticación segura"),
    ("A.8.6", "Gestión de la capacidad"),
    ("A.8.7", "Protección contra malware"),
    ("A.8.8", "Gestión de vulnerabilidades técnicas"),
    ("A.8.9", "Gestión de la configuración"),
    ("A.8.10", "Eliminación de información"),
    ("A.8.11", "Enmascaramiento de datos"),
    ("A.8.12", "Prevención de fuga de datos (DLP)"),
    ("A.8.13", "Respaldo de información (Backups)"),
    ("A.8.14", "Redundancia de recursos TIC"),
    ("A.8.15", "Registro (Logging)"),
    ("A.8.16", "Monitorización de actividades"),
    ("A.8.17", "Sincronización de relojes"),
    ("A.8.18", "Uso de utilidades privilegiadas"),
    ("A.8.19", "Instalación de software en sistemas operativos"),
    ("A.8.20", "Seguridad de las redes"),
    ("A.8.21", "Seguridad de los servicios de red"),
    ("A.8.22", "Segregación de redes"),
    ("A.8.23", "Filtrado web"),
    ("A.8.24", "Uso de criptografía"),
    ("A.8.25", "Ciclo de vida de desarrollo seguro"),
    ("A.8.26", "Requisitos de seguridad en aplicaciones"),
    ("A.8.27", "Principios de arquitectura e ingeniería de sistemas seguros"),
    ("A.8.28", "Codificación segura"),
    ("A.8.29", "Pruebas de seguridad en desarrollo y aceptación"),
    ("A.8.30", "Desarrollo externalizado"),
    ("A.8.31", "Separación de entornos de desarrollo, prueba y producción"),
    ("A.8.32", "Gestión de cambios"),
    ("A.8.33", "Información de prueba (Testing)"),
    ("A.8.34", "Protección de sistemas de información en auditorías"),
]

itil_v4_practices = [
    # Prácticas de Gestión General (14)
    ("G-01", "Gestión de la arquitectura (Architecture management)"),
    ("G-02", "Mejora continua (Continual improvement)"),
    ("G-03", "Gestión de la seguridad de la información (Information security management)"),
    ("G-04", "Gestión del conocimiento (Knowledge management)"),
    ("G-05", "Medición y reporte (Measurement and reporting)"),
    ("G-06", "Gestión del cambio organizacional (Organisational change management)"),
    ("G-07", "Gestión del portafolio (Portfolio management)"),
    ("G-08", "Gestión de proyectos (Project management)"),
    ("G-09", "Gestión de relaciones (Relationship management)"),
    ("G-10", "Gestión de riesgos (Risk management)"),
    ("G-11", "Gestión financiera de servicios (Service financial management)"),
    ("G-12", "Gestión de la estrategia (Strategy management)"),
    ("G-13", "Gestión de proveedores (Supplier management)"),
    ("G-14", "Gestión de la fuerza laboral y talento (Workforce and talent management)"),
    
    # Prácticas de Gestión de Servicios (17)
    ("S-01", "Gestión de la disponibilidad (Availability management)"),
    ("S-02", "Análisis de negocio (Business analysis)"),
    ("S-03", "Gestión de capacidad y rendimiento (Capacity and performance management)"),
    ("S-04", "Habilitación del cambio (Change enablement)"),
    ("S-05", "Gestión de incidentes (Incident management)"),
    ("S-06", "Gestión de activos de TI (IT asset management)"),
    ("S-07", "Monitorización y gestión de eventos (Monitoring and event management)"),
    ("S-08", "Gestión de problemas (Problem management)"),
    ("S-09", "Gestión de liberaciones (Release management)"),
    ("S-10", "Gestión del catálogo de servicios (Service catalogue management)"),
    ("S-11", "Gestión de la configuración de servicios (Service configuration management)"),
    ("S-12", "Gestión de la continuidad del servicio (Service continuity management)"),
    ("S-13", "Diseño del servicio (Service design)"),
    ("S-14", "Mesa de servicios (Service desk)"),
    ("S-15", "Gestión del nivel de servicio (Service level management)"),
    ("S-16", "Gestión de solicitudes de servicio (Service request management)"),
    ("S-17", "Validación y pruebas del servicio (Service validation and testing)"),
    
    # Prácticas de Gestión Técnica (3)
    ("T-01", "Gestión del despliegue (Deployment management)"),
    ("T-02", "Gestión de infraestructura y plataformas (Infrastructure and platform management)"),
    ("T-03", "Desarrollo y gestión de software (Software development and management)"),
]


def seed_production_frameworks():
    """
    Carga los frameworks base (master data) en la base de datos 
    si no existen.
    """
    print("Seeding production frameworks...")
    
    frameworks_added = False
    
    # --- ISO 27001:2022 ---
    if not Framework.query.filter_by(name='ISO27001:2022').first():
        print("Creando Framework ISO27001:2022...")
        iso_framework = Framework(
            name='ISO27001:2022',
            description='Controles del Anexo A para la seguridad de la información, ciberseguridad y protección de la privacidad.',
            link='https://www.iso.org/standard/82875.html',
            is_custom=False  # ¡Importante!
        )
        
        # Añadir los 93 controles
        for control_id, name in iso_27001_controls:
            iso_framework.framework_controls.append(FrameworkControl(
                control_id=control_id, 
                name=name
            ))
        
        db.session.add(iso_framework)
        frameworks_added = True
        print(f"ISO27001:2022 añadido con {len(iso_27001_controls)} controles.")

    # --- ITIL v4 ---
    if not Framework.query.filter_by(name='ITIL v4').first():
        print("Creando Framework ITIL v4...")
        itil_framework = Framework(
            name='ITIL v4',
            description='Marco de trabajo para la Gestión de Servicios de TI (ITSM) centrado en la co-creación de valor a través de 34 prácticas.',
            link='https://www.axelos.com/best-practice-solutions/itil',
            is_custom=False
        )
        
        # Añadir las 34 prácticas
        for control_id, name in itil_v4_practices:
            itil_framework.framework_controls.append(FrameworkControl(
                control_id=control_id, 
                name=name
            ))

        db.session.add(itil_framework)
        frameworks_added = True
        print(f"ITIL v4 añadido con {len(itil_v4_practices)} prácticas.")

    # --- Commit a la base de datos ---
    if frameworks_added:
        try:
            db.session.commit()
            print("Frameworks de producción añadidos (seeded) correctamente.")
        except Exception as e:
            db.session.rollback()
            print(f"Error al añadir frameworks de producción: {e}")
    else:
        print("Los frameworks de producción ya existen. No se tomó ninguna acción.")