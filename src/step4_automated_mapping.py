#!/usr/bin/env python
"""
Part 11 - Step 4: Automated XBRL Concept Mapping
Automatically map PDF table labels to XBRL concepts using semantic similarity
"""

from pathlib import Path
import pandas as pd
import json
from difflib import SequenceMatcher
import re
from datetime import datetime

class AutomatedXBRLMapper:
    """Automatically map PDF labels to XBRL concepts using semantic similarity"""
    
    def __init__(self):
        # Common financial statement synonyms
        self.synonym_groups = {
            'revenue': ['revenue', 'sales', 'income', 'receipts', 'net sales', 'total revenue'],
            'cost': ['cost', 'expense', 'cogs', 'cost of sales', 'cost of goods sold'],
            'profit': ['profit', 'margin', 'earnings', 'income'],
            'assets': ['assets', 'resources', 'holdings'],
            'liabilities': ['liabilities', 'debt', 'obligations', 'payables'],
            'equity': ['equity', 'shareholders equity', 'stockholders equity', 'capital'],
            'cash': ['cash', 'equivalents', 'liquid assets'],
            'current': ['current', 'short term', 'near term'],
            'operating': ['operating', 'operational', 'core business'],
            'eps': ['eps', 'earnings per share', 'per share earnings']
        }
        
        self.mapping_results = []
    
    def normalize_label(self, text):
        """Normalize text for comparison"""
        if not text:
            return ""
        
        # Convert to lowercase and remove special characters
        text = str(text).lower()
        text = re.sub(r'[^\w\s]', ' ', text)
        text = ' '.join(text.split())  # Remove extra spaces
        return text
    
    def get_semantic_keywords(self, text):
        """Extract semantic keywords from text"""
        normalized = self.normalize_label(text)
        keywords = set()
        
        # Add original words
        words = normalized.split()
        keywords.update(words)
        
        # Add synonym matches
        for category, synonyms in self.synonym_groups.items():
            for synonym in synonyms:
                if synonym in normalized:
                    keywords.add(category)
        
        return keywords
    
    def calculate_similarity(self, xbrl_concept, pdf_label):
        """Calculate similarity between XBRL concept and PDF label"""
        
        # Direct string similarity
        direct_similarity = SequenceMatcher(None, 
                                          self.normalize_label(xbrl_concept),
                                          self.normalize_label(pdf_label)).ratio()
        
        # Semantic keyword similarity
        xbrl_keywords = self.get_semantic_keywords(xbrl_concept)
        pdf_keywords = self.get_semantic_keywords(pdf_label)
        
        if len(xbrl_keywords.union(pdf_keywords)) > 0:
            semantic_similarity = len(xbrl_keywords.intersection(pdf_keywords)) / len(xbrl_keywords.union(pdf_keywords))
        else:
            semantic_similarity = 0
        
        # Combined score (weighted)
        combined_score = (direct_similarity * 0.4) + (semantic_similarity * 0.6)
        
        return {
            'direct': direct_similarity,
            'semantic': semantic_similarity,
            'combined': combined_score
        }
    
    def auto_map_concepts(self, xbrl_concepts, pdf_labels):
        """Automatically map XBRL concepts to PDF labels"""
        
        mappings = {}
        
        print(f"\nAutomated Mapping Results:")
        print("-" * 60)
        
        for xbrl_concept in xbrl_concepts:
            best_matches = []
            
            # Calculate similarity with all PDF labels
            for pdf_label in pdf_labels:
                similarity = self.calculate_similarity(xbrl_concept, pdf_label)
                best_matches.append({
                    'pdf_label': pdf_label,
                    'similarity': similarity['combined'],
                    'direct': similarity['direct'],
                    'semantic': similarity['semantic']
                })
            
            # Sort by similarity score
            best_matches.sort(key=lambda x: x['similarity'], reverse=True)
            top_match = best_matches[0]
            
            # Only accept matches above threshold
            if top_match['similarity'] > 0.3:  # 30% similarity threshold
                mappings[xbrl_concept] = {
                    'best_match': top_match['pdf_label'],
                    'similarity': top_match['similarity'],
                    'confidence': 'High' if top_match['similarity'] > 0.7 else 'Medium'
                }
                
                print(f"✓ {xbrl_concept:.<35} → {top_match['pdf_label']:<25} ({top_match['similarity']:.3f})")
                
                # Store detailed results
                self.mapping_results.append({
                    'xbrl_concept': xbrl_concept,
                    'pdf_label': top_match['pdf_label'],
                    'similarity_score': top_match['similarity'],
                    'direct_similarity': top_match['direct'],
                    'semantic_similarity': top_match['semantic'],
                    'confidence': mappings[xbrl_concept]['confidence'],
                    'top_3_matches': best_matches[:3]
                })
            else:
                mappings[xbrl_concept] = {
                    'best_match': None,
                    'similarity': top_match['similarity'],
                    'confidence': 'Low'
                }
                print(f"✗ {xbrl_concept:.<35} → No good match ({top_match['similarity']:.3f})")
        
        return mappings
    
    def load_xbrl_concepts(self):
        """Load XBRL concepts from Step 2 results"""
        csv_path = Path("data/validation/xbrl_financial_data.csv")
        
        if not csv_path.exists():
            print("✗ XBRL data not found. Run step2_parse_xbrl.py first")
            return []
        
        df = pd.read_csv(csv_path)
        return df['concept'].tolist()
    
    def load_pdf_labels(self):
        """Load PDF table labels from all extracted tables"""
        pdf_labels = set()
        
        # Load from pipeline tables
        pipeline_dir = Path("data/parsed/Apple_SEA/tables")
        if pipeline_dir.exists():
            for csv_file in pipeline_dir.glob("*.csv"):
                try:
                    df = pd.read_csv(csv_file)
                    if not df.empty and len(df.columns) > 0:
                        # Extract labels from first column
                        labels = df.iloc[:, 0].dropna().astype(str).tolist()
                        pdf_labels.update(labels)
                except:
                    continue
        
        # Load from Docling tables
        docling_dir = Path("data/parsed/docling/tables/Apple_SEA")
        if docling_dir.exists():
            for csv_file in docling_dir.glob("*.csv"):
                try:
                    df = pd.read_csv(csv_file)
                    if not df.empty and len(df.columns) > 0:
                        labels = df.iloc[:, 0].dropna().astype(str).tolist()
                        pdf_labels.update(labels)
                except:
                    continue
        
        # Filter out non-financial labels
        financial_labels = []
        financial_keywords = ['revenue', 'sales', 'income', 'profit', 'assets', 'liabilities', 
                            'equity', 'cash', 'debt', 'cost', 'expense', 'earnings', 'eps']
        
        for label in pdf_labels:
            normalized = self.normalize_label(label)
            if any(keyword in normalized for keyword in financial_keywords):
                financial_labels.append(label)
        
        return financial_labels[:50]  # Limit to top 50 for demo
    
    def save_results(self, mappings):
        """Save automated mapping results"""
        output_dir = Path("data/validation")
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Save mapping dictionary
        mappings_path = output_dir / "automated_mappings.json"
        with open(mappings_path, 'w') as f:
            json.dump(mappings, f, indent=2, default=str)
        print(f"\n✓ Saved mappings to: {mappings_path}")
        
        # Save detailed results
        if self.mapping_results:
            results_df = pd.DataFrame(self.mapping_results)
            results_path = output_dir / "mapping_analysis.csv"
            results_df.to_csv(results_path, index=False)
            print(f"✓ Saved analysis to: {results_path}")
        
        # Generate report
        self.generate_mapping_report(mappings)
    
    def generate_mapping_report(self, mappings):
        """Generate automated mapping report"""
        
        report = []
        report.append("# Automated XBRL Concept Mapping Report")
        report.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report.append("")
        
        # Summary statistics
        total_concepts = len(mappings)
        successful_mappings = len([m for m in mappings.values() if m['best_match'] is not None])
        high_confidence = len([m for m in mappings.values() if m.get('confidence') == 'High'])
        
        report.append("## Summary")
        report.append(f"- Total XBRL concepts: {total_concepts}")
        report.append(f"- Successfully mapped: {successful_mappings} ({successful_mappings/total_concepts*100:.1f}%)")
        report.append(f"- High confidence mappings: {high_confidence} ({high_confidence/total_concepts*100:.1f}%)")
        report.append("")
        
        # Successful mappings
        successful = [(k, v) for k, v in mappings.items() if v['best_match'] is not None]
        if successful:
            report.append("## Successful Mappings")
            for concept, mapping in successful:
                confidence = mapping.get('confidence', 'Unknown')
                score = mapping.get('similarity', 0)
                report.append(f"- **{concept}** → {mapping['best_match']}")
                report.append(f"  - Confidence: {confidence} (Score: {score:.3f})")
            report.append("")
        
        # Failed mappings
        failed = [(k, v) for k, v in mappings.items() if v['best_match'] is None]
        if failed:
            report.append("## Failed Mappings")
            for concept, mapping in failed:
                score = mapping.get('similarity', 0)
                report.append(f"- **{concept}** (Best score: {score:.3f})")
            report.append("")
        
        report.append("## Methodology")
        report.append("- **Direct Similarity**: String matching using sequence similarity")
        report.append("- **Semantic Similarity**: Keyword-based matching using financial synonyms")
        report.append("- **Combined Score**: Weighted combination (40% direct, 60% semantic)")
        report.append("- **Threshold**: Minimum 30% similarity for acceptance")
        
        report_text = "\n".join(report)
        report_path = Path("data/validation/automated_mapping_report.md")
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(report_text)
        print(f"✓ Saved report to: {report_path}")

def main():
    """Main function"""
    
    print("="*70)
    print(" Part 11 - Step 4: Automated XBRL Concept Mapping ".center(70))
    print("="*70)
    
    # Initialize mapper
    mapper = AutomatedXBRLMapper()
    
    # Load data
    print("\n[1/4] Loading XBRL concepts...")
    xbrl_concepts = mapper.load_xbrl_concepts()
    print(f"✓ Loaded {len(xbrl_concepts)} XBRL concepts")
    
    print("\n[2/4] Loading PDF table labels...")
    pdf_labels = mapper.load_pdf_labels()
    print(f"✓ Loaded {len(pdf_labels)} PDF labels")
    
    if not xbrl_concepts or not pdf_labels:
        print("✗ Insufficient data for mapping")
        return
    
    # Perform automated mapping
    print("\n[3/4] Performing automated mapping...")
    mappings = mapper.auto_map_concepts(xbrl_concepts, pdf_labels)
    
    # Save results
    print("\n[4/4] Saving results...")
    mapper.save_results(mappings)
    
    # Summary
    successful = len([m for m in mappings.values() if m['best_match'] is not None])
    print("\n" + "="*70)
    print(f"✅ Step 4 Complete!")
    print(f"   Successfully mapped {successful}/{len(xbrl_concepts)} concepts")
    print(f"   Check data/validation/ for detailed results")
    print("="*70)

if __name__ == "__main__":
    main()