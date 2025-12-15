#!/usr/bin/env python3
"""
PDF Report Generation Service for TabletTracker
Generates comprehensive PO lifecycle reports with detailed production metrics
"""

import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak, KeepTogether
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
    
    def __init__(self, db_path: str = None):
        from config import Config
        self.db_path = db_path or Config.DATABASE_PATH
        self.styles = getSampleStyleSheet()
        self._setup_custom_styles()
    
    def _setup_custom_styles(self):
        """Setup custom paragraph styles for the report"""
        self.styles.add(ParagraphStyle(
            name='CustomTitle',
            parent=self.styles['Heading1'],
            fontSize=16,
            spaceAfter=8,
            alignment=TA_CENTER,
            textColor=colors.HexColor('#0B2E33')
        ))
        
        self.styles.add(ParagraphStyle(
            name='SectionHeader',
            parent=self.styles['Heading2'],
            fontSize=12,
            spaceBefore=6,
            spaceAfter=4,
            textColor=colors.HexColor('#4F7C82')
        ))
        
        self.styles.add(ParagraphStyle(
            name='MetricLabel',
            parent=self.styles['Normal'],
            fontSize=9,
            textColor=colors.HexColor('#666666')
        ))
        
        self.styles.add(ParagraphStyle(
            name='MetricValue',
            parent=self.styles['Normal'],
            fontSize=10,
            fontName='Helvetica-Bold',
            textColor=colors.HexColor('#0B2E33')
        ))

    def get_db_connection(self) -> sqlite3.Connection:
        """Get database connection with row factory"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def generate_production_report(self, start_date: str = None, end_date: str = None, po_numbers: List[str] = None, tablet_type_id: int = None) -> bytes:
        """
        Generate comprehensive production report
        
        Args:
            start_date: Start date in YYYY-MM-DD format (optional)
            end_date: End date in YYYY-MM-DD format (optional) 
            po_numbers: List of specific PO numbers to include (optional)
            tablet_type_id: Filter by specific tablet type ID (optional)
            
        Returns:
            bytes: PDF content
            
        Raises:
            Exception: If report generation fails
        """
        buffer = None
        try:
            buffer = io.BytesIO()
            doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=50, leftMargin=50, 
                                  topMargin=30, bottomMargin=25)
            
            story = []
            
            # Report header (more compact)
            story.append(Paragraph("Production Cycle Report", self.styles['CustomTitle']))
            # Get current time in Eastern Time
            eastern = ZoneInfo("America/New_York")
            now_et = datetime.now(eastern)
            # Determine if DST is in effect (EDT) or not (EST)
            tz_abbr = "EDT" if now_et.dst() else "EST"
            story.append(Paragraph(f"Generated on {now_et.strftime('%B %d, %Y at %I:%M %p')} {tz_abbr}", self.styles['Normal']))
            
            if start_date or end_date:
                date_range = f"Period: {start_date or 'Beginning'} to {end_date or 'Present'}"
                story.append(Paragraph(date_range, self.styles['Normal']))
            
            story.append(Spacer(1, 10))
            
            # Get report data
            report_data = self._get_report_data(start_date, end_date, po_numbers, tablet_type_id)
            
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
        except Exception as e:
            # Ensure buffer is closed if it was created
            if buffer:
                try:
                    buffer.close()
                except:
                    pass
            raise Exception(f"Failed to generate production report: {str(e)}")

    def _get_report_data(self, start_date: str = None, end_date: str = None, po_numbers: List[str] = None, tablet_type_id: int = None) -> Dict:
        """Gather comprehensive data for the report"""
        conn = None
        try:
            conn = self.get_db_connection()
            
            # Build date filter (filter by submission date, not PO creation date)
            date_filter = ""
            params = []
            
            if start_date:
                date_filter += " AND COALESCE(ws.submission_date, DATE(ws.created_at)) >= ?"
                params.append(start_date)
            if end_date:
                date_filter += " AND COALESCE(ws.submission_date, DATE(ws.created_at)) <= ?"
                params.append(end_date)
            
            # Build PO filter
            po_filter = ""
            if po_numbers:
                placeholders = ",".join(["?" for _ in po_numbers])
                po_filter = f" AND po.po_number IN ({placeholders})"
                params.extend(po_numbers)
            
            # Build tablet type filter
            tablet_filter = ""
            if tablet_type_id:
                tablet_filter = """
                    AND EXISTS (
                        SELECT 1 FROM warehouse_submissions ws2
                        JOIN product_details pd2 ON ws2.product_name = pd2.product_name
                        LEFT JOIN bags b ON ws2.bag_id = b.id
                        LEFT JOIN small_boxes sb ON b.small_box_id = sb.id
                        LEFT JOIN receiving r ON sb.receiving_id = r.id
                        WHERE (ws2.bag_id IS NOT NULL AND r.po_id = po.id OR ws2.assigned_po_id = po.id)
                        AND pd2.tablet_type_id = ?
                    )
                """
                params.append(tablet_type_id)
            
            # Get PO data with all related information
            # Filter by submissions that match date/tablet type criteria
            po_query = f"""
            SELECT DISTINCT
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
            LEFT JOIN warehouse_submissions ws ON (
                po.id = ws.assigned_po_id OR 
                EXISTS (
                    SELECT 1 FROM bags b
                    JOIN small_boxes sb ON b.small_box_id = sb.id
                    JOIN receiving r ON sb.receiving_id = r.id
                    WHERE ws.bag_id = b.id AND r.po_id = po.id
                )
            )
            LEFT JOIN product_details pd ON ws.product_name = pd.product_name
            WHERE 1=1 {date_filter} {po_filter} {tablet_filter}
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
                # Convert to dict immediately 
                po_dict = dict(po)
                po_data = self._get_detailed_po_data(conn, po_dict['id'])
                
                # Calculate pack time if we have delivery and completion data
                pack_time = self._calculate_pack_time(po_data)
                if pack_time:
                    total_pack_times.append(pack_time)
                
                report_data['pos'].append(po_data)
                
                # Update summary stats
                report_data['summary']['total_ordered'] += po_data.get('ordered_quantity', 0) or 0
                report_data['summary']['total_produced'] += po_data.get('current_good_count', 0) or 0
                report_data['summary']['total_damaged'] += po_data.get('current_damaged_count', 0) or 0
            
            # Calculate average pack time
            if total_pack_times:
                report_data['summary']['average_pack_time'] = sum(total_pack_times) / len(total_pack_times)
            
            # Calculate efficiency rate
            if report_data['summary']['total_ordered'] > 0:
                total_processed = report_data['summary']['total_produced'] + report_data['summary']['total_damaged']
                report_data['summary']['efficiency_rate'] = (report_data['summary']['total_produced'] / total_processed * 100) if total_processed > 0 else 0
            
            # Get product breakdown
            report_data['summary']['product_breakdown'] = self._get_product_breakdown(conn, start_date, end_date, po_numbers, tablet_type_id)
            
            return report_data
        finally:
            if conn:
                try:
                    conn.close()
                except:
                    pass

    def _get_product_breakdown(self, conn: sqlite3.Connection, start_date: str = None, end_date: str = None, po_numbers: List[str] = None, tablet_type_id: int = None) -> List[Dict]:
        """Get breakdown of ordered/produced/damaged by product/tablet type"""
        # Build filters
        date_filter = ""
        params = []
        
        if start_date:
            date_filter += " AND COALESCE(ws.submission_date, DATE(ws.created_at)) >= ?"
            params.append(start_date)
        if end_date:
            date_filter += " AND COALESCE(ws.submission_date, DATE(ws.created_at)) <= ?"
            params.append(end_date)
        
        po_filter = ""
        if po_numbers:
            placeholders = ",".join(["?" for _ in po_numbers])
            po_filter = f" AND po.po_number IN ({placeholders})"
            params.extend(po_numbers)
        
        tablet_filter = ""
        if tablet_type_id:
            tablet_filter = " AND pd.tablet_type_id = ?"
            params.append(tablet_type_id)
        
        # Query to get ordered quantities by product from PO lines
        # Group by inventory_item_id to match how counts are calculated/stored
        # Join with product_details and warehouse_submissions to filter by date and tablet type
        query = f"""
        SELECT 
            COALESCE(pl.line_item_name, 'Unknown') as product_name,
            pl.inventory_item_id,
            SUM(pl.quantity_ordered) as ordered,
            SUM(pl.good_count) as produced,
            SUM(pl.damaged_count) as damaged
        FROM po_lines pl
        JOIN purchase_orders po ON pl.po_id = po.id
        LEFT JOIN warehouse_submissions ws ON (
            po.id = ws.assigned_po_id OR 
            EXISTS (
                SELECT 1 FROM bags b
                JOIN small_boxes sb ON b.small_box_id = sb.id
                JOIN receiving r ON sb.receiving_id = r.id
                WHERE ws.bag_id = b.id AND r.po_id = po.id
            )
        )
        LEFT JOIN product_details pd ON ws.product_name = pd.product_name
        WHERE 1=1 {date_filter} {po_filter} {tablet_filter}
        GROUP BY pl.inventory_item_id, pl.line_item_name
        ORDER BY ordered DESC
        """
        
        results = conn.execute(query, params).fetchall()
        
        breakdown = []
        for row in results:
            breakdown.append({
                'product_name': row['product_name'],
                'ordered': row['ordered'] or 0,
                'produced': row['produced'] or 0,
                'damaged': row['damaged'] or 0
            })
        
        return breakdown

    def _get_detailed_po_data(self, conn: sqlite3.Connection, po_id: int) -> Dict:
        """Get detailed data for a specific PO"""
        try:
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
            
            # Warehouse submissions (support both new bag-based and legacy PO-based)
            submissions = conn.execute("""
                SELECT ws.*, pd.packages_per_display, pd.tablets_per_package, tt.tablet_type_name
                FROM warehouse_submissions ws
                LEFT JOIN product_details pd ON ws.product_name = pd.product_name
                LEFT JOIN tablet_types tt ON pd.tablet_type_id = tt.id
                LEFT JOIN bags b ON ws.bag_id = b.id
                LEFT JOIN small_boxes sb ON b.small_box_id = sb.id
                LEFT JOIN receiving r ON sb.receiving_id = r.id
                WHERE (ws.bag_id IS NOT NULL AND r.po_id = ?) OR (ws.bag_id IS NULL AND ws.assigned_po_id = ?)
                ORDER BY ws.created_at
            """, (po_id, po_id)).fetchall()
            
            # Convert to dicts to avoid sqlite3.Row issues
            po_dict = dict(po) if po else {}
            lines_list = [dict(line) for line in lines] if lines else []
            shipment_dict = dict(shipment) if shipment else None
            submissions_list = [dict(sub) for sub in submissions] if submissions else []
            
            # Calculate round numbers for each line item
            current_po_number = po_dict.get('po_number') if po_dict else None
            if current_po_number:
                for line in lines_list:
                    round_number = None
                    inventory_item_id = line.get('inventory_item_id')
                    
                    if inventory_item_id:
                        # Find all POs containing this inventory_item_id, ordered by PO number (oldest first)
                        pos_with_item = conn.execute('''
                            SELECT DISTINCT po.po_number, po.id
                            FROM purchase_orders po
                            JOIN po_lines pl ON po.id = pl.po_id
                            WHERE pl.inventory_item_id = ?
                            ORDER BY po.po_number ASC
                        ''', (inventory_item_id,)).fetchall()
                        
                        # Find the position of current PO in this list (1-indexed = round number)
                        for idx, po_row in enumerate(pos_with_item, start=1):
                            if po_row['po_number'] == current_po_number:
                                round_number = idx
                                break
                    
                    line['round_number'] = round_number
            
            # Calculate production breakdown
            production_breakdown = self._calculate_production_breakdown(submissions_list)
            
            return {
                **po_dict,
                'lines': lines_list,
                'shipment': shipment_dict,
                'submissions': submissions_list,
                'production_breakdown': production_breakdown,
                'pack_time_days': self._calculate_pack_time({'po': po_dict, 'shipment': shipment_dict, 'submissions': submissions_list})
            }
        except Exception as e:
            # Return minimal data structure if error occurs
            return {
                'id': po_id,
                'po_number': f'PO-{po_id}',
                'lines': [],
                'shipment': None,
                'submissions': [],
                'production_breakdown': {},
                'pack_time_days': None
            }

    def _calculate_production_breakdown(self, submissions: List[Dict]) -> Dict:
        """Calculate detailed production breakdown from submissions"""
        breakdown = {
            'total_displays': 0,
            'total_packages': 0,
            'total_loose': 0,
            'total_damaged': 0,
            'total_tablets': 0,
            'by_product': {},
            'by_employee': {},
            'production_timeline': []
        }
        
        for sub in submissions:
            # Calculate total tablets for this submission first
            displays_tablets = (sub['displays_made'] or 0) * (sub['packages_per_display'] or 0) * (sub['tablets_per_package'] or 0)
            package_tablets = (sub['packs_remaining'] or 0) * (sub['tablets_per_package'] or 0)
            loose_tablets = sub['loose_tablets'] or 0
            damaged_tablets = sub['damaged_tablets'] or 0
            total_tablets = displays_tablets + package_tablets + loose_tablets + damaged_tablets
            
            # Overall totals
            breakdown['total_displays'] += sub['displays_made'] or 0
            breakdown['total_packages'] += sub['packs_remaining'] or 0
            breakdown['total_loose'] += sub['loose_tablets'] or 0
            breakdown['total_damaged'] += sub['damaged_tablets'] or 0
            breakdown['total_tablets'] += total_tablets
            
            # By product
            product = sub['product_name']
            if product not in breakdown['by_product']:
                breakdown['by_product'][product] = {
                    'displays': 0, 'packages': 0, 'loose': 0, 'damaged': 0, 'total_tablets': 0
                }
            breakdown['by_product'][product]['displays'] += sub['displays_made'] or 0
            breakdown['by_product'][product]['packages'] += sub['packs_remaining'] or 0
            breakdown['by_product'][product]['loose'] += sub['loose_tablets'] or 0
            breakdown['by_product'][product]['damaged'] += sub['damaged_tablets'] or 0
            breakdown['by_product'][product]['total_tablets'] += total_tablets
            
            # By employee
            employee = sub['employee_name']
            if employee not in breakdown['by_employee']:
                breakdown['by_employee'][employee] = {
                    'submissions': 0, 'displays': 0, 'total_tablets': 0
                }
            breakdown['by_employee'][employee]['submissions'] += 1
            breakdown['by_employee'][employee]['displays'] += sub['displays_made'] or 0
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
        
        summary_table = Table(summary_data, colWidths=[2.5*inch, 1.8*inch])
        summary_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4F7C82')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 4),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 3),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        
        story.append(KeepTogether([summary_table, Spacer(1, 6)]))
        
        # Product Breakdown Table
        if summary.get('product_breakdown'):
            product_heading = Paragraph("Production Breakdown by Product", self.styles['SectionHeader'])
            
            # Create header with subheader for Remaining column
            remaining_header = Paragraph("<font color='white'>Remaining</font><br/><font size=7 color='white'>Ordered - (Produced + Damaged)</font>", self.styles['Normal'])
            
            product_data = [['Product', 'Ordered', 'Produced', 'Damaged', remaining_header]]
            
            for product in summary['product_breakdown']:
                ordered = product['ordered'] or 0
                produced = product['produced'] or 0
                damaged = product['damaged'] or 0
                remaining = ordered - (produced + damaged)
                product_data.append([
                    product['product_name'],
                    f"{ordered:,}",
                    f"{produced:,}",
                    f"{damaged:,}",
                    f"{remaining:,}"
                ])
            
            # Add totals row
            total_remaining = summary['total_ordered'] - (summary['total_produced'] + summary['total_damaged'])
            product_data.append([
                'TOTAL',
                f"{summary['total_ordered']:,}",
                f"{summary['total_produced']:,}",
                f"{summary['total_damaged']:,}",
                f"{total_remaining:,}"
            ])
            
            product_table = Table(product_data, colWidths=[2.5*inch, 1.1*inch, 1.1*inch, 1.1*inch, 1.2*inch])
            product_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4F7C82')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('ALIGN', (1, 0), (-1, -1), 'CENTER'),  # Center numbers
                ('ALIGN', (4, 0), (-1, -1), 'CENTER'),  # Center remaining column
                ('VALIGN', (4, 0), (4, 0), 'MIDDLE'),  # Vertically center remaining header
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 10),
                ('FONTSIZE', (0, 1), (-1, -1), 9),
                ('TOPPADDING', (0, 0), (-1, -1), 3),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
                ('BACKGROUND', (0, 1), (-1, -2), colors.beige),
                # Totals row styling
                ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#93B1B5')),
                ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
                ('LINEABOVE', (0, -1), (-1, -1), 2, colors.black),
                ('GRID', (0, 0), (-1, -1), 1, colors.black)
            ]))
            
            story.append(KeepTogether([product_heading, product_table, Spacer(1, 6)]))
        
        return story

    def _create_po_detailed_report(self, po_data: Dict) -> List:
        """Create detailed report for individual PO"""
        story = []
        
        # PO Header
        story.append(Paragraph(f"Purchase Order: {po_data['po_number']}", self.styles['SectionHeader']))
        
        # Basic PO Info
        # Use Paragraph for tablet type to enable text wrapping within cell
        tablet_type_text = po_data.get('tablet_type', 'N/A')
        # Always use Paragraph to ensure wrapping works properly
        tablet_type_para = Paragraph(tablet_type_text, self.styles['Normal'])
        
        po_info_data = [
            ['PO Number', po_data['po_number']],
            ['Zoho PO ID', po_data.get('zoho_po_id', 'N/A')],
            ['Tablet Type', tablet_type_para],
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
        
        po_info_table = Table(po_info_data, colWidths=[1.8*inch, 4.2*inch])
        po_info_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#B8E3E9')),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),  # Align to top for multi-line cells
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('TOPPADDING', (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
            ('LEFTPADDING', (1, 2), (1, 2), 3),  # Extra padding for tablet type cell
            ('RIGHTPADDING', (1, 2), (1, 2), 3),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        
        story.append(KeepTogether([po_info_table, Spacer(1, 6)]))
        
        # Line Items with Round Numbers
        if po_data.get('lines'):
            line_items_heading = Paragraph("Line Items", self.styles['Heading3'])
            
            line_items_data = [['Product Name', 'Round', 'Ordered', 'Good', 'Damaged', 'Remaining']]
            for line in po_data['lines']:
                remaining = (line.get('quantity_ordered', 0) or 0) - (line.get('good_count', 0) or 0) - (line.get('damaged_count', 0) or 0)
                round_text = f"Round {line.get('round_number', 'N/A')}" if line.get('round_number') else 'N/A'
                # Use Paragraph for product names to enable text wrapping within cell
                product_name = line.get('line_item_name', 'Unknown')
                # Always use Paragraph to ensure wrapping works properly
                product_name_para = Paragraph(product_name, self.styles['Normal'])
                line_items_data.append([
                    product_name_para,
                    round_text,
                    f"{(line.get('quantity_ordered', 0) or 0):,}",
                    f"{(line.get('good_count', 0) or 0):,}",
                    f"{(line.get('damaged_count', 0) or 0):,}",
                    f"{remaining:,}"
                ])
            
            line_items_table = Table(line_items_data, colWidths=[2.5*inch, 0.8*inch, 0.9*inch, 0.9*inch, 0.9*inch, 0.9*inch])
            line_items_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4F7C82')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),  # Align to top for multi-line cells
                ('ALIGN', (1, 0), (-1, -1), 'CENTER'),  # Center numbers and round
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 9),
                ('FONTSIZE', (0, 1), (-1, -1), 8),
                ('TOPPADDING', (0, 0), (-1, -1), 3),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
                ('LEFTPADDING', (0, 1), (0, -1), 3),  # Extra padding for product name cells
                ('RIGHTPADDING', (0, 1), (0, -1), 3),
                ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                ('GRID', (0, 0), (-1, -1), 1, colors.black)
            ]))
            
            story.append(KeepTogether([line_items_heading, line_items_table, Spacer(1, 6)]))
        
        # Shipment Information
        if po_data.get('shipment'):
            shipment_heading = Paragraph("Shipment Information", self.styles['Heading3'])
            shipment = po_data['shipment']
            
            shipment_data = [
                ['Carrier', shipment.get('carrier', 'N/A')],
                ['Tracking Number', shipment.get('tracking_number', 'N/A')],
                ['Shipped Date', shipment.get('shipped_date', 'N/A')],
                ['Estimated Delivery', shipment.get('estimated_delivery', 'N/A')],
                ['Actual Delivery', shipment.get('actual_delivery', 'N/A')],
                ['Tracking Status', shipment.get('tracking_status', 'N/A')]
            ]
            
            shipment_table = Table(shipment_data, colWidths=[1.8*inch, 2.5*inch])
            shipment_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#93B1B5')),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('TOPPADDING', (0, 0), (-1, -1), 3),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
                ('GRID', (0, 0), (-1, -1), 1, colors.black)
            ]))
            
            story.append(KeepTogether([shipment_heading, shipment_table, Spacer(1, 6)]))
        
        # Production Breakdown
        if po_data.get('production_breakdown'):
            breakdown_heading = Paragraph("Production Breakdown", self.styles['Heading3'])
            breakdown = po_data['production_breakdown']
            
            breakdown_data = [
                ['Production Metric', 'Quantity'],
                ['Total Displays Made', f"{breakdown['total_displays']:,}"],
                ['Packages Remaining', f"{breakdown['total_packages']:,}"],
                ['Loose Tablets', f"{breakdown['total_loose']:,}"],
                ['Damaged Tablets', f"{breakdown['total_damaged']:,}"],
                ['Total Tablets', f"{breakdown['total_tablets']:,}"],
                ['Total Submissions', f"{len(po_data['submissions']):,}"]
            ]
            
            breakdown_table = Table(breakdown_data, colWidths=[2.2*inch, 2*inch])
            breakdown_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4F7C82')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 10),
                ('FONTSIZE', (0, 1), (-1, -1), 9),
                ('TOPPADDING', (0, 0), (-1, -1), 3),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
                ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                ('GRID', (0, 0), (-1, -1), 1, colors.black)
            ]))
            
            story.append(KeepTogether([breakdown_heading, breakdown_table, Spacer(1, 6)]))
            
            # By Employee breakdown  
            if breakdown['by_employee']:
                employee_heading = Paragraph("Production by Employee", self.styles['Heading4'])
                
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
                    ('FONTSIZE', (0, 0), (-1, -1), 8),
                    ('TOPPADDING', (0, 0), (-1, -1), 2),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
                    ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                    ('GRID', (0, 0), (-1, -1), 1, colors.black)
                ]))
                
                story.append(KeepTogether([employee_heading, employee_table, Spacer(1, 4)]))
        
        return story

    def _create_overall_metrics(self, report_data: Dict) -> List:
        """Create overall production metrics section"""
        story = []
        story.append(Paragraph("Overall Production Metrics", self.styles['SectionHeader']))
        
        # Calculate aggregate metrics across all POs
        all_products = {}
        pack_times = []
        
        for po in report_data['pos']:
            if po.get('pack_time_days'):
                pack_times.append(po['pack_time_days'])
            
            if po.get('production_breakdown'):
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
            pack_time_heading = Paragraph("Pack Time Analysis", self.styles['Heading3'])
            
            pack_time_data = [
                ['Metric', 'Days'],
                ['Minimum Pack Time', f"{min(pack_times)} days"],
                ['Maximum Pack Time', f"{max(pack_times)} days"],
                ['Average Pack Time', f"{sum(pack_times)/len(pack_times):.1f} days"],
                ['Median Pack Time', f"{sorted(pack_times)[len(pack_times)//2]:.1f} days"]
            ]
            
            pack_time_table = Table(pack_time_data, colWidths=[2.5*inch, 1.8*inch])
            pack_time_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4F7C82')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('TOPPADDING', (0, 0), (-1, -1), 3),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
                ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                ('GRID', (0, 0), (-1, -1), 1, colors.black)
            ]))
            
            story.append(KeepTogether([pack_time_heading, pack_time_table, Spacer(1, 6)]))
        
        # Product performance summary
        if all_products:
            prod_heading = Paragraph("Product Performance Summary", self.styles['Heading3'])
            
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
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('TOPPADDING', (0, 0), (-1, -1), 2),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
                ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                ('GRID', (0, 0), (-1, -1), 1, colors.black)
            ]))
            
            story.append(KeepTogether([prod_heading, prod_table]))
        
        return story

    def generate_vendor_report(self, start_date: str = None, end_date: str = None, po_numbers: List[str] = None, tablet_type_id: int = None) -> bytes:
        """
        Generate vendor report - single page with only Production Breakdown by Product table
        
        Args:
            start_date: Start date in YYYY-MM-DD format (optional)
            end_date: End date in YYYY-MM-DD format (optional) 
            po_numbers: List of specific PO numbers to include (optional)
            tablet_type_id: Filter by specific tablet type ID (optional)
            
        Returns:
            bytes: PDF content
            
        Raises:
            Exception: If report generation fails
        """
        buffer = None
        try:
            buffer = io.BytesIO()
            doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=50, leftMargin=50, 
                                  topMargin=30, bottomMargin=25)
            
            story = []
            
            # Report header
            story.append(Paragraph("Vendor Report", self.styles['CustomTitle']))
            # Get current time in Eastern Time
            eastern = ZoneInfo("America/New_York")
            now_et = datetime.now(eastern)
            # Determine if DST is in effect (EDT) or not (EST)
            tz_abbr = "EDT" if now_et.dst() else "EST"
            story.append(Paragraph(f"Generated on {now_et.strftime('%B %d, %Y at %I:%M %p')} {tz_abbr}", self.styles['Normal']))
            
            if start_date or end_date:
                date_range = f"Period: {start_date or 'Beginning'} to {end_date or 'Present'}"
                story.append(Paragraph(date_range, self.styles['Normal']))
            
            story.append(Spacer(1, 12))
            
            # Get report data
            report_data = self._get_report_data(start_date, end_date, po_numbers, tablet_type_id)
            
            # Only include Production Breakdown by Product table
            summary = report_data['summary']
            
            if summary.get('product_breakdown') and len(summary['product_breakdown']) > 0:
                product_heading = Paragraph("Production Breakdown by Product", self.styles['SectionHeader'])
                
                # Create header with subheader for Remaining column
                remaining_header = Paragraph("<font color='white'>Remaining</font><br/><font size=7 color='white'>Ordered - (Produced + Damaged)</font>", self.styles['Normal'])
                
                product_data = [['Product', 'Ordered', 'Produced', 'Damaged', remaining_header]]
                
                for product in summary['product_breakdown']:
                    ordered = product['ordered'] or 0
                    produced = product['produced'] or 0
                    damaged = product['damaged'] or 0
                    remaining = ordered - (produced + damaged)
                    product_data.append([
                        product['product_name'],
                        f"{ordered:,}",
                        f"{produced:,}",
                        f"{damaged:,}",
                        f"{remaining:,}"
                    ])
                
                # Add totals row
                total_remaining = summary['total_ordered'] - (summary['total_produced'] + summary['total_damaged'])
                product_data.append([
                    'TOTAL',
                    f"{summary['total_ordered']:,}",
                    f"{summary['total_produced']:,}",
                    f"{summary['total_damaged']:,}",
                    f"{total_remaining:,}"
                ])
                
                product_table = Table(product_data, colWidths=[2.5*inch, 1.1*inch, 1.1*inch, 1.1*inch, 1.2*inch])
                product_table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4F7C82')),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                    ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                    ('ALIGN', (1, 0), (-1, -1), 'CENTER'),  # Center numbers
                    ('ALIGN', (4, 0), (-1, -1), 'CENTER'),  # Center remaining column
                    ('VALIGN', (4, 0), (4, 0), 'MIDDLE'),  # Vertically center remaining header
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, 0), 10),
                    ('FONTSIZE', (0, 1), (-1, -1), 9),
                    ('TOPPADDING', (0, 0), (-1, -1), 4),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                    ('BACKGROUND', (0, 1), (-1, -2), colors.beige),
                    # Totals row styling
                    ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#93B1B5')),
                    ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
                    ('LINEABOVE', (0, -1), (-1, -1), 2, colors.black),
                    ('GRID', (0, 0), (-1, -1), 1, colors.black)
                ]))
                
                story.append(KeepTogether([product_heading, product_table]))
            else:
                # Show message if no data available
                story.append(Paragraph("No production data available for the selected criteria.", self.styles['Normal']))
                story.append(Spacer(1, 10))
                story.append(Paragraph("Please adjust your date range or PO selection.", self.styles['Normal']))
            
            # Build PDF
            doc.build(story)
            buffer.seek(0)
            return buffer.getvalue()
        except Exception as e:
            # Ensure buffer is closed if it was created
            if buffer:
                try:
                    buffer.close()
                except:
                    pass
            raise Exception(f"Failed to generate vendor report: {str(e)}")

# Example usage and testing
    def generate_receive_report(self, receive_id: int) -> bytes:
        """
        Generate report for a specific receive showing all bags and their submission counts
        
        Args:
            receive_id: The receive ID to generate report for
            
        Returns:
            PDF report as bytes
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        try:
            # Get receive details
            receive = cursor.execute('''
                SELECT r.*, po.po_number, po.id as po_id, r.receive_name
                FROM receiving r
                LEFT JOIN purchase_orders po ON r.po_id = po.id
                WHERE r.id = ?
            ''', (receive_id,)).fetchone()
            
            if not receive:
                raise ValueError(f'Receive with ID {receive_id} not found')
            
            # Convert sqlite3.Row to dict
            receive = dict(receive)
            
            # Use stored receive_name, or build it if missing (for legacy records)
            if receive.get('receive_name'):
                receive_name = receive['receive_name']
            elif receive.get('po_number'):
                # Calculate receive_number for legacy records
                receive_number_result = cursor.execute('''
                    SELECT COUNT(*) + 1 as receive_number
                    FROM receiving r2
                    WHERE r2.po_id = ?
                    AND (r2.received_date < ? 
                         OR (r2.received_date = ? AND r2.id < ?))
                ''', (receive['po_id'], receive.get('received_date'), receive.get('received_date'), receive['id'])).fetchone()
                receive_number = dict(receive_number_result)['receive_number'] if receive_number_result else 1
                receive_name = f"{receive['po_number']}-{receive_number}"
            else:
                receive_name = f"Receive-{receive_id}"
            
            # Get all bags with their submission counts
            bags_data = cursor.execute('''
                SELECT b.*, 
                       tt.tablet_type_name,
                       sb.box_number,
                       -- Machine count
                       COALESCE((
                           SELECT SUM(COALESCE(ws.tablets_pressed_into_cards, 0))
                           FROM warehouse_submissions ws
                           WHERE ws.bag_id = b.id AND ws.submission_type = 'machine'
                       ), 0) as machine_count,
                       -- Packaged count (only packaged, not bag counts)
                       COALESCE((
                           SELECT SUM(
                               (COALESCE(ws.displays_made, 0) * COALESCE(pd.packages_per_display, 0) * COALESCE(pd.tablets_per_package, 0)) +
                               (COALESCE(ws.packs_remaining, 0) * COALESCE(pd.tablets_per_package, 0)) +
                               COALESCE(ws.loose_tablets, 0)
                           )
                           FROM warehouse_submissions ws
                           LEFT JOIN product_details pd ON ws.product_name = pd.product_name
                           WHERE ws.bag_id = b.id AND ws.submission_type = 'packaged'
                       ), 0) as packaged_count,
                       -- Damaged count
                       COALESCE((
                           SELECT SUM(COALESCE(ws.damaged_tablets, 0))
                           FROM warehouse_submissions ws
                           WHERE ws.bag_id = b.id
                       ), 0) as damaged_count
                FROM bags b
                JOIN small_boxes sb ON b.small_box_id = sb.id
                JOIN tablet_types tt ON b.tablet_type_id = tt.id
                WHERE sb.receiving_id = ?
                ORDER BY sb.box_number, b.bag_number
            ''', (receive_id,)).fetchall()
            
            # Convert all sqlite3.Row objects to dictionaries
            bags_data = [dict(bag) for bag in bags_data]
            
            # Create PDF
            buffer = io.BytesIO()
            doc = SimpleDocTemplate(buffer, pagesize=letter, topMargin=0.5*inch, bottomMargin=0.5*inch)
            elements = []
            
            # Title
            title_style = ParagraphStyle(
                'CustomTitle',
                parent=self.styles['Heading1'],
                fontSize=18,
                textColor=colors.HexColor('#1e40af'),
                spaceAfter=12,
                alignment=1  # Center
            )
            elements.append(Paragraph(f"Receive Report: {receive_name}", title_style))
            elements.append(Spacer(1, 0.1*inch))
            
            # Receive info
            info_data = [
                ['PO Number:', receive.get('po_number', 'N/A')],
                ['Received Date:', receive.get('received_date') or 'N/A'],
                ['Received By:', receive.get('received_by') or 'N/A'],
                ['Total Boxes:', str(len(set(bag.get('box_number') for bag in bags_data)))],
                ['Total Bags:', str(len(bags_data))]
            ]
            
            info_table = Table(info_data, colWidths=[1.5*inch, 4*inch])
            info_table.setStyle(TableStyle([
                ('ALIGN', (0, 0), (0, -1), 'RIGHT'),
                ('ALIGN', (1, 0), (1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 10),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ]))
            elements.append(info_table)
            elements.append(Spacer(1, 0.3*inch))
            
            # Bags table
            table_data = [[
                'Box', 'Bag', 'Product', 'Received', 'Machine', 'Packaged', 'Damaged', 'Total Counted', 'Remaining', '% Complete'
            ]]
            
            for bag in bags_data:
                received = bag.get('bag_label_count', 0) or 0
                machine = bag.get('machine_count', 0) or 0
                packaged = bag.get('packaged_count', 0) or 0
                damaged = bag.get('damaged_count', 0) or 0
                total_counted = machine + packaged
                remaining = received - total_counted
                percent_complete = round((total_counted / received * 100) if received > 0 else 0, 1)
                
                table_data.append([
                    str(bag.get('box_number', '')),
                    str(bag.get('bag_number', '')),
                    bag.get('tablet_type_name', 'N/A'),
                    f"{received:,}",
                    f"{machine:,}",
                    f"{packaged:,}",
                    f"{damaged:,}",
                    f"{total_counted:,}",
                    f"{remaining:,}",
                    f"{percent_complete}%"
                ])
            
            table = Table(table_data, colWidths=[0.4*inch, 0.4*inch, 1.8*inch, 0.7*inch, 0.7*inch, 0.7*inch, 0.6*inch, 0.8*inch, 0.7*inch, 0.7*inch])
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1e40af')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 9),
                ('FONTSIZE', (0, 1), (-1, -1), 8),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
                ('BACKGROUND', (0, 1), (-1, -1), colors.white),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f3f4f6')]),
            ]))
            elements.append(table)
            
            # Build PDF
            doc.build(elements)
            pdf_content = buffer.getvalue()
            buffer.close()
            
            return pdf_content
            
        finally:
            if conn:
                try:
                    conn.close()
                except:
                    pass

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