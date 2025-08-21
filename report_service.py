#!/usr/bin/env python3
"""
PDF Report Generation Service for TabletTracker
Generates comprehensive PO lifecycle reports with detailed production metrics
"""

import sqlite3
from datetime import datetime, timedelta
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.graphics.shapes import Drawing, Rect
from reportlab.graphics.charts.linecharts import HorizontalLineChart
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics import renderPDF
import io
from typing import Dict, List, Optional, Tuple

class ProductionReportGenerator:
    """Generates comprehensive production cycle reports with detailed metrics"""
    
    def __init__(self, db_path: str = 'tablet_counter.db'):
        self.db_path = db_path
        self.styles = getSampleStyleSheet()
        self._setup_custom_styles()
    
    def _setup_custom_styles(self):
        """Setup custom paragraph styles for the report"""
        self.styles.add(ParagraphStyle(
            name='CustomTitle',
            parent=self.styles['Heading1'],
            fontSize=24,
            spaceAfter=30,
            alignment=TA_CENTER,
            textColor=colors.HexColor('#0B2E33')
        ))
        
        self.styles.add(ParagraphStyle(
            name='SectionHeader',
            parent=self.styles['Heading2'],
            fontSize=16,
            spaceBefore=20,
            spaceAfter=10,
            textColor=colors.HexColor('#4F7C82')
        ))
        
        self.styles.add(ParagraphStyle(
            name='MetricLabel',
            parent=self.styles['Normal'],
            fontSize=10,
            textColor=colors.HexColor('#666666')
        ))
        
        self.styles.add(ParagraphStyle(
            name='MetricValue',
            parent=self.styles['Normal'],
            fontSize=12,
            fontName='Helvetica-Bold',
            textColor=colors.HexColor('#0B2E33')
        ))

    def get_db_connection(self) -> sqlite3.Connection:
        """Get database connection with row factory"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def generate_production_report(self, start_date: str = None, end_date: str = None, po_numbers: List[str] = None) -> bytes:
        """
        Generate comprehensive production report
        
        Args:
            start_date: Start date in YYYY-MM-DD format (optional)
            end_date: End date in YYYY-MM-DD format (optional) 
            po_numbers: List of specific PO numbers to include (optional)
            
        Returns:
            bytes: PDF content
        """
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=72, leftMargin=72, 
                              topMargin=72, bottomMargin=18)
        
        story = []
        
        # Report header
        story.append(Paragraph("Production Cycle Report", self.styles['CustomTitle']))
        story.append(Paragraph(f"Generated on {datetime.now().strftime('%B %d, %Y at %I:%M %p')}", self.styles['Normal']))
        
        if start_date or end_date:
            date_range = f"Period: {start_date or 'Beginning'} to {end_date or 'Present'}"
            story.append(Paragraph(date_range, self.styles['Normal']))
        
        story.append(Spacer(1, 20))
        
        # Get report data
        report_data = self._get_report_data(start_date, end_date, po_numbers)
        
        # Executive Summary
        story.extend(self._create_executive_summary(report_data))
        
        # Individual PO Reports
        for po_data in report_data['pos']:
            story.extend(self._create_po_detailed_report(po_data))
            story.append(PageBreak())
        
        # Overall Production Metrics
        story.extend(self._create_overall_metrics(report_data))
        
        # Build PDF
        doc.build(story)
        buffer.seek(0)
        return buffer.getvalue()

    def _get_report_data(self, start_date: str = None, end_date: str = None, po_numbers: List[str] = None) -> Dict:
        """Gather comprehensive data for the report"""
        conn = self.get_db_connection()
        
        # Build date filter
        date_filter = ""
        params = []
        
        if start_date:
            date_filter += " AND po.created_at >= ?"
            params.append(start_date)
        if end_date:
            date_filter += " AND po.created_at <= ?"
            params.append(end_date + " 23:59:59")
        
        # Build PO filter
        po_filter = ""
        if po_numbers:
            placeholders = ",".join(["?" for _ in po_numbers])
            po_filter = f" AND po.po_number IN ({placeholders})"
            params.extend(po_numbers)
        
        # Get PO data with all related information
        po_query = f"""
        SELECT 
            po.*,
            s.tracking_number,
            s.carrier,
            s.shipped_date,
            s.estimated_delivery,
            s.actual_delivery,
            s.tracking_status,
            s.delivered_at,
            COUNT(DISTINCT ws.id) as total_submissions,
            MIN(ws.created_at) as first_submission,
            MAX(ws.created_at) as last_submission
        FROM purchase_orders po
        LEFT JOIN shipments s ON po.id = s.po_id
        LEFT JOIN warehouse_submissions ws ON po.id = ws.assigned_po_id
        WHERE 1=1 {date_filter} {po_filter}
        GROUP BY po.id
        ORDER BY po.created_at DESC
        """
        
        pos = conn.execute(po_query, params).fetchall()
        
        report_data = {
            'pos': [],
            'summary': {
                'total_pos': len(pos),
                'total_ordered': 0,
                'total_produced': 0,
                'total_damaged': 0,
                'average_pack_time': 0,
                'efficiency_rate': 0
            }
        }
        
        total_pack_times = []
        
        for po in pos:
            po_data = self._get_detailed_po_data(conn, po['id'])
            
            # Calculate pack time if we have delivery and completion data
            pack_time = self._calculate_pack_time(po_data)
            if pack_time:
                total_pack_times.append(pack_time)
            
            report_data['pos'].append(po_data)
            
            # Update summary stats
            report_data['summary']['total_ordered'] += po_data['ordered_quantity'] or 0
            report_data['summary']['total_produced'] += po_data['current_good_count'] or 0
            report_data['summary']['total_damaged'] += po_data['current_damaged_count'] or 0
        
        # Calculate average pack time
        if total_pack_times:
            report_data['summary']['average_pack_time'] = sum(total_pack_times) / len(total_pack_times)
        
        # Calculate efficiency rate
        if report_data['summary']['total_ordered'] > 0:
            total_processed = report_data['summary']['total_produced'] + report_data['summary']['total_damaged']
            report_data['summary']['efficiency_rate'] = (report_data['summary']['total_produced'] / total_processed * 100) if total_processed > 0 else 0
        
        conn.close()
        return report_data

    def _get_detailed_po_data(self, conn: sqlite3.Connection, po_id: int) -> Dict:
        """Get detailed data for a specific PO"""
        # Base PO info
        po = conn.execute("SELECT * FROM purchase_orders WHERE id = ?", (po_id,)).fetchone()
        
        # PO lines
        lines = conn.execute("""
            SELECT pl.*, tt.tablet_type_name
            FROM po_lines pl
            LEFT JOIN tablet_types tt ON pl.inventory_item_id = tt.inventory_item_id
            WHERE pl.po_id = ?
            ORDER BY pl.line_item_name
        """, (po_id,)).fetchall()
        
        # Shipment info
        shipment = conn.execute("SELECT * FROM shipments WHERE po_id = ?", (po_id,)).fetchone()
        
        # Warehouse submissions
        submissions = conn.execute("""
            SELECT ws.*, pd.packages_per_display, pd.tablets_per_package, tt.tablet_type_name
            FROM warehouse_submissions ws
            LEFT JOIN product_details pd ON ws.product_name = pd.product_name
            LEFT JOIN tablet_types tt ON pd.tablet_type_id = tt.id
            WHERE ws.assigned_po_id = ?
            ORDER BY ws.created_at
        """, (po_id,)).fetchall()
        
        # Calculate production breakdown
        production_breakdown = self._calculate_production_breakdown(submissions)
        
        return {
            **dict(po),
            'lines': [dict(line) for line in lines],
            'shipment': dict(shipment) if shipment else None,
            'submissions': [dict(sub) for sub in submissions],
            'production_breakdown': production_breakdown,
            'pack_time_days': self._calculate_pack_time({'po': po, 'shipment': shipment, 'submissions': submissions})
        }

    def _calculate_production_breakdown(self, submissions: List[sqlite3.Row]) -> Dict:
        """Calculate detailed production breakdown from submissions"""
        breakdown = {
            'total_displays': 0,
            'total_packages': 0,
            'total_loose': 0,
            'total_damaged': 0,
            'by_product': {},
            'by_employee': {},
            'production_timeline': []
        }
        
        for sub in submissions:
            # Overall totals
            breakdown['total_displays'] += sub['displays_made'] or 0
            breakdown['total_packages'] += sub['packs_remaining'] or 0
            breakdown['total_loose'] += sub['loose_tablets'] or 0
            breakdown['total_damaged'] += sub['damaged_tablets'] or 0
            
            # By product
            product = sub['product_name']
            if product not in breakdown['by_product']:
                breakdown['by_product'][product] = {
                    'displays': 0, 'packages': 0, 'loose': 0, 'damaged': 0
                }
            breakdown['by_product'][product]['displays'] += sub['displays_made'] or 0
            breakdown['by_product'][product]['packages'] += sub['packs_remaining'] or 0
            breakdown['by_product'][product]['loose'] += sub['loose_tablets'] or 0
            breakdown['by_product'][product]['damaged'] += sub['damaged_tablets'] or 0
            
            # By employee
            employee = sub['employee_name']
            if employee not in breakdown['by_employee']:
                breakdown['by_employee'][employee] = {
                    'submissions': 0, 'displays': 0, 'total_tablets': 0
                }
            breakdown['by_employee'][employee]['submissions'] += 1
            breakdown['by_employee'][employee]['displays'] += sub['displays_made'] or 0
            
            # Calculate total tablets for this submission
            displays_tablets = (sub['displays_made'] or 0) * (sub['packages_per_display'] or 0) * (sub['tablets_per_package'] or 0)
            package_tablets = (sub['packs_remaining'] or 0) * (sub['tablets_per_package'] or 0)
            loose_tablets = sub['loose_tablets'] or 0
            total_tablets = displays_tablets + package_tablets + loose_tablets
            
            breakdown['by_employee'][employee]['total_tablets'] += total_tablets
            
            # Timeline entry
            breakdown['production_timeline'].append({
                'date': sub['created_at'],
                'employee': employee,
                'product': product,
                'displays': sub['displays_made'] or 0,
                'tablets_processed': total_tablets
            })
        
        return breakdown

    def _calculate_pack_time(self, po_data: Dict) -> Optional[float]:
        """Calculate pack time in days from delivery to completion"""
        if isinstance(po_data, dict) and 'po' in po_data:
            # Called from _get_detailed_po_data
            po = po_data['po']
            shipment = po_data['shipment']
            submissions = po_data['submissions']
        else:
            # Called from _get_report_data
            po = po_data
            shipment = None
            submissions = []
        
        # Get delivery date from shipment
        delivery_date = None
        if shipment and shipment.get('actual_delivery'):
            delivery_date = datetime.strptime(shipment['actual_delivery'], '%Y-%m-%d')
        elif shipment and shipment.get('delivered_at'):
            delivery_date = datetime.strptime(shipment['delivered_at'], '%Y-%m-%d')
        
        # Get completion date (last submission or when PO was marked complete)
        completion_date = None
        if submissions:
            last_submission = max(submissions, key=lambda x: x.get('created_at', ''))
            if last_submission.get('created_at'):
                completion_date = datetime.strptime(last_submission['created_at'][:10], '%Y-%m-%d')
        
        # If PO is complete but no submissions, use updated_at
        if not completion_date and po.get('internal_status') == 'Complete':
            completion_date = datetime.strptime(po['updated_at'][:10], '%Y-%m-%d')
        
        if delivery_date and completion_date:
            return (completion_date - delivery_date).days
        
        return None

    def _create_executive_summary(self, report_data: Dict) -> List:
        """Create executive summary section"""
        story = []
        story.append(Paragraph("Executive Summary", self.styles['SectionHeader']))
        
        summary = report_data['summary']
        
        # Summary stats table
        summary_data = [
            ['Metric', 'Value'],
            ['Total Purchase Orders', f"{summary['total_pos']:,}"],
            ['Total Tablets Ordered', f"{summary['total_ordered']:,}"],
            ['Total Tablets Produced', f"{summary['total_produced']:,}"],
            ['Total Tablets Damaged', f"{summary['total_damaged']:,}"],
            ['Production Efficiency', f"{summary['efficiency_rate']:.1f}%"],
            ['Average Pack Time', f"{summary['average_pack_time']:.1f} days" if summary['average_pack_time'] else "N/A"]
        ]
        
        summary_table = Table(summary_data, colWidths=[3*inch, 2*inch])
        summary_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4F7C82')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        
        story.append(summary_table)
        story.append(Spacer(1, 20))
        
        return story

    def _create_po_detailed_report(self, po_data: Dict) -> List:
        """Create detailed report for individual PO"""
        story = []
        
        # PO Header
        story.append(Paragraph(f"Purchase Order: {po_data['po_number']}", self.styles['SectionHeader']))
        
        # Basic PO Info
        po_info_data = [
            ['PO Number', po_data['po_number']],
            ['Zoho PO ID', po_data.get('zoho_po_id', 'N/A')],
            ['Tablet Type', po_data.get('tablet_type', 'N/A')],
            ['Status', po_data.get('internal_status', 'Unknown')],
            ['Zoho Status', po_data.get('zoho_status', 'N/A')],
            ['Created Date', po_data['created_at'][:10] if po_data.get('created_at') else 'N/A'],
            ['Ordered Quantity', f"{po_data.get('ordered_quantity', 0):,} tablets"],
            ['Good Count', f"{po_data.get('current_good_count', 0):,} tablets"],
            ['Damaged Count', f"{po_data.get('current_damaged_count', 0):,} tablets"],
            ['Remaining', f"{po_data.get('remaining_quantity', 0):,} tablets"]
        ]
        
        if po_data.get('pack_time_days'):
            po_info_data.append(['Pack Time', f"{po_data['pack_time_days']} days"])
        
        po_info_table = Table(po_info_data, colWidths=[2*inch, 3*inch])
        po_info_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#B8E3E9')),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        
        story.append(po_info_table)
        story.append(Spacer(1, 15))
        
        # Shipment Information
        if po_data.get('shipment'):
            story.append(Paragraph("Shipment Information", self.styles['Heading3']))
            shipment = po_data['shipment']
            
            shipment_data = [
                ['Carrier', shipment.get('carrier', 'N/A')],
                ['Tracking Number', shipment.get('tracking_number', 'N/A')],
                ['Shipped Date', shipment.get('shipped_date', 'N/A')],
                ['Estimated Delivery', shipment.get('estimated_delivery', 'N/A')],
                ['Actual Delivery', shipment.get('actual_delivery', 'N/A')],
                ['Tracking Status', shipment.get('tracking_status', 'N/A')]
            ]
            
            shipment_table = Table(shipment_data, colWidths=[2*inch, 3*inch])
            shipment_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#93B1B5')),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                ('GRID', (0, 0), (-1, -1), 1, colors.black)
            ]))
            
            story.append(shipment_table)
            story.append(Spacer(1, 15))
        
        # Production Breakdown
        if po_data.get('production_breakdown'):
            story.append(Paragraph("Production Breakdown", self.styles['Heading3']))
            breakdown = po_data['production_breakdown']
            
            breakdown_data = [
                ['Production Metric', 'Quantity'],
                ['Total Displays Made', f"{breakdown['total_displays']:,}"],
                ['Packages Remaining', f"{breakdown['total_packages']:,}"],
                ['Loose Tablets', f"{breakdown['total_loose']:,}"],
                ['Damaged Tablets', f"{breakdown['total_damaged']:,}"],
                ['Total Submissions', f"{len(po_data['submissions']):,}"]
            ]
            
            breakdown_table = Table(breakdown_data, colWidths=[2.5*inch, 2.5*inch])
            breakdown_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4F7C82')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 10),
                ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                ('GRID', (0, 0), (-1, -1), 1, colors.black)
            ]))
            
            story.append(breakdown_table)
            story.append(Spacer(1, 15))
            
            # By Product breakdown
            if breakdown['by_product']:
                story.append(Paragraph("Production by Product", self.styles['Heading4']))
                
                product_data = [['Product', 'Displays', 'Packages', 'Loose', 'Damaged']]
                for product, data in breakdown['by_product'].items():
                    product_data.append([
                        product,
                        str(data['displays']),
                        str(data['packages']), 
                        str(data['loose']),
                        str(data['damaged'])
                    ])
                
                product_table = Table(product_data, colWidths=[2*inch, 1*inch, 1*inch, 1*inch, 1*inch])
                product_table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#93B1B5')),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                    ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, -1), 9),
                    ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                    ('GRID', (0, 0), (-1, -1), 1, colors.black)
                ]))
                
                story.append(product_table)
                story.append(Spacer(1, 15))
            
            # By Employee breakdown  
            if breakdown['by_employee']:
                story.append(Paragraph("Production by Employee", self.styles['Heading4']))
                
                employee_data = [['Employee', 'Submissions', 'Displays', 'Total Tablets']]
                for employee, data in breakdown['by_employee'].items():
                    employee_data.append([
                        employee,
                        str(data['submissions']),
                        str(data['displays']),
                        f"{data['total_tablets']:,}"
                    ])
                
                employee_table = Table(employee_data, colWidths=[2*inch, 1*inch, 1*inch, 1.5*inch])
                employee_table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#93B1B5')),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                    ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, -1), 9),
                    ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                    ('GRID', (0, 0), (-1, -1), 1, colors.black)
                ]))
                
                story.append(employee_table)
                story.append(Spacer(1, 15))
        
        return story

    def _create_overall_metrics(self, report_data: Dict) -> List:
        """Create overall production metrics section"""
        story = []
        story.append(Paragraph("Overall Production Metrics", self.styles['SectionHeader']))
        
        # Calculate aggregate metrics across all POs
        all_employees = {}
        all_products = {}
        pack_times = []
        
        for po in report_data['pos']:
            if po.get('pack_time_days'):
                pack_times.append(po['pack_time_days'])
            
            if po.get('production_breakdown'):
                # Aggregate employee stats
                for emp, data in po['production_breakdown']['by_employee'].items():
                    if emp not in all_employees:
                        all_employees[emp] = {'submissions': 0, 'displays': 0, 'tablets': 0}
                    all_employees[emp]['submissions'] += data['submissions']
                    all_employees[emp]['displays'] += data['displays']
                    all_employees[emp]['tablets'] += data['total_tablets']
                
                # Aggregate product stats
                for prod, data in po['production_breakdown']['by_product'].items():
                    if prod not in all_products:
                        all_products[prod] = {'displays': 0, 'packages': 0, 'loose': 0, 'damaged': 0}
                    all_products[prod]['displays'] += data['displays']
                    all_products[prod]['packages'] += data['packages']
                    all_products[prod]['loose'] += data['loose']
                    all_products[prod]['damaged'] += data['damaged']
        
        # Pack time distribution
        if pack_times:
            story.append(Paragraph("Pack Time Analysis", self.styles['Heading3']))
            
            pack_time_data = [
                ['Metric', 'Days'],
                ['Minimum Pack Time', f"{min(pack_times)} days"],
                ['Maximum Pack Time', f"{max(pack_times)} days"],
                ['Average Pack Time', f"{sum(pack_times)/len(pack_times):.1f} days"],
                ['Median Pack Time', f"{sorted(pack_times)[len(pack_times)//2]:.1f} days"]
            ]
            
            pack_time_table = Table(pack_time_data, colWidths=[3*inch, 2*inch])
            pack_time_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4F7C82')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                ('GRID', (0, 0), (-1, -1), 1, colors.black)
            ]))
            
            story.append(pack_time_table)
            story.append(Spacer(1, 15))
        
        # Top performing employees
        if all_employees:
            story.append(Paragraph("Employee Performance Summary", self.styles['Heading3']))
            
            # Sort by total tablets processed
            top_employees = sorted(all_employees.items(), key=lambda x: x[1]['tablets'], reverse=True)[:10]
            
            emp_data = [['Employee', 'Total Submissions', 'Total Displays', 'Total Tablets']]
            for emp, data in top_employees:
                emp_data.append([
                    emp,
                    str(data['submissions']),
                    str(data['displays']),
                    f"{data['tablets']:,}"
                ])
            
            emp_table = Table(emp_data, colWidths=[2*inch, 1.2*inch, 1.2*inch, 1.6*inch])
            emp_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4F7C82')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                ('GRID', (0, 0), (-1, -1), 1, colors.black)
            ]))
            
            story.append(emp_table)
            story.append(Spacer(1, 15))
        
        # Product performance summary
        if all_products:
            story.append(Paragraph("Product Performance Summary", self.styles['Heading3']))
            
            prod_data = [['Product', 'Total Displays', 'Total Packages', 'Loose Tablets', 'Damaged']]
            for prod, data in sorted(all_products.items()):
                prod_data.append([
                    prod,
                    str(data['displays']),
                    str(data['packages']),
                    str(data['loose']),
                    str(data['damaged'])
                ])
            
            prod_table = Table(prod_data, colWidths=[2*inch, 1*inch, 1*inch, 1*inch, 1*inch])
            prod_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4F7C82')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                ('GRID', (0, 0), (-1, -1), 1, colors.black)
            ]))
            
            story.append(prod_table)
        
        return story

# Example usage and testing
if __name__ == "__main__":
    generator = ProductionReportGenerator()
    
    # Generate report for last 30 days
    end_date = datetime.now()
    start_date = end_date - timedelta(days=30)
    
    pdf_content = generator.generate_production_report(
        start_date=start_date.strftime('%Y-%m-%d'),
        end_date=end_date.strftime('%Y-%m-%d')
    )
    
    # Save to file for testing
    with open('production_report_test.pdf', 'wb') as f:
        f.write(pdf_content)
    
    print("Test report generated: production_report_test.pdf")