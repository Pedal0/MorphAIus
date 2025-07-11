"""
Système de validation et correction automatique simplifié utilisant uniquement RepoMix.
Plus simple, plus fiable, plus efficace que l'approche MCP.
"""
import os
import logging
from pathlib import Path
from src.api.openrouter_api import call_openrouter_api
from src.mcp.simple_codebase_client import create_simple_codebase_client
from src.utils.prompt_loader import get_agent_prompt, get_system_prompt_with_best_practices

def validate_and_fix_with_repomix(target_directory, api_key=None, model=None, user_prompt=None, reformulated_prompt=None, progress_callback=None):
    """
    Validation et correction automatique ultra-simplifiée avec RepoMix uniquement.
    
    Args:
        target_directory: Répertoire du projet généré
        api_key: Clé API OpenRouter
        model: Modèle à utiliser
        user_prompt: Prompt original de l'utilisateur
        reformulated_prompt: Prompt reformulé
        progress_callback: Fonction de callback pour le progrès
      Returns:
        tuple: (success, message)
    """
    try:
        if progress_callback:
            progress_callback(9, "🔍 RepoMix codebase analysis...", 95)
        
        if not api_key or not model:
            return False, "API key and model required for validation."
        
        # Étape 1: Analyser avec RepoMix
        codebase_client = create_simple_codebase_client()
        
        if not codebase_client.repomix_available:
            # Fallback: installer RepoMix automatiquement
            if progress_callback:
                progress_callback(9, "📦 Installing RepoMix - this will take longer the first time...", 90)
            
            install_success = codebase_client._install_repomix()
            if not install_success:
                return False, "Failed to install RepoMix for codebase analysis"
            
            codebase_client.repomix_available = True
        
        if progress_callback:
            progress_callback(9, "📊 Analyzing complete codebase...", 96)
        
        # Obtenir l'analyse complète
        success, codebase_analysis = codebase_client.get_codebase_analysis(
            target_directory, 
            output_format="markdown", 
            include_summary=True
        )
        
        if not success:
            return False, f"RepoMix analysis failed: {codebase_analysis}"
        
        if progress_callback:
            progress_callback(9, "🧠 AI validation and correction...", 97)
          # Étape 2: IA analyse et corrige
        validation_prompt = get_agent_prompt(
            'simple_validation_agent',
            'simple_validation_prompt',
            user_prompt=user_prompt or 'Not specified',
            reformulated_prompt=reformulated_prompt or 'Not specified',
            repomix_content=codebase_analysis[:25000] + ("..." if len(codebase_analysis) > 25000 else "")
        )
        
        # Load system prompt
        system_prompt = get_agent_prompt('simple_validation_agent', 'simple_validation_system_prompt')
        
        # Appeler l'IA
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": validation_prompt}
        ]
        
        response = call_openrouter_api(api_key, model, messages, temperature=0.2, max_retries=2)
        
        if response and response.get("choices"):
            ai_response = response["choices"][0]["message"]["content"]
            
            if progress_callback:
                progress_callback(9, "⚡ Applying fixes...", 98)
              # Étape 3: Appliquer les corrections
            if "🔧" in ai_response or "APPLY_FIXES" in ai_response:
                # SAFETY CHECK: Make sure we don't apply fixes if AI says no issues found
                if ("NO ISSUES FOUND" in ai_response.upper() or 
                    "ALL CODE VALIDATED" in ai_response.upper() or 
                    "CODE VALIDATION PASSED" in ai_response.upper() or
                    "EVERYTHING IS GOOD" in ai_response.upper() or
                    "✅" in ai_response and ("NO ISSUES" in ai_response.upper() or "NO PROBLEMS" in ai_response.upper())):
                    message = "✅ All code validated - no issues found (safety check prevented unnecessary fixes)"
                    logging.info("RepoMix validation passed - safety check prevented fix application when no issues found")
                else:
                    fixes_applied = apply_simple_fixes(target_directory, ai_response)
                
                    # CRITIQUE: Nettoyage final après toutes les corrections
                    if fixes_applied > 0:
                        if progress_callback:
                            progress_callback(9, "🧹 Final cleanup of corrected files...", 99)
                        
                        final_cleanup_count = clean_markdown_artifacts(target_directory)
                        if final_cleanup_count > 0:
                            logging.info(f"🧹 Final cleanup: removed markdown artifacts from {final_cleanup_count} additional files after fixes")
                        
                        message = f"✅ {fixes_applied} issues automatically fixed + {final_cleanup_count} files cleaned"
                        logging.info(f"Applied {fixes_applied} RepoMix-based fixes with final cleanup")
                    else:
                        message = f"Issues detected but no fixes applied"
                        logging.warning("AI found issues but couldn't apply fixes")
            else:
                message = "✅ All code validated - no issues found"
                logging.info("RepoMix validation passed - no issues found")
            
            if progress_callback:
                progress_callback(10, f"✅ Validation complete: {message}", 100)
            
            return True, message
        else:
            return False, "Failed to get AI validation response"
            
    except Exception as e:
        logging.error(f"Error during RepoMix validation: {e}")
        return False, str(e)


def apply_simple_fixes(target_directory, ai_response):
    """
    Applique les corrections identifiées par l'IA.
    
    Args:
        target_directory: Répertoire du projet
        ai_response: Réponse de l'IA avec les corrections
    
    Returns:
        int: Nombre de corrections appliquées
    """
    try:
        fixes_applied = 0
        target_path = Path(target_directory)
        
        # SAFETY CHECK: Don't apply fixes if response indicates no issues
        if ("NO ISSUES FOUND" in ai_response.upper() or 
            "ALL CODE VALIDATED" in ai_response.upper() or 
            "CODE VALIDATION PASSED" in ai_response.upper() or
            "EVERYTHING IS GOOD" in ai_response.upper() or
            "✅" in ai_response and ("NO ISSUES" in ai_response.upper() or "NO PROBLEMS" in ai_response.upper())):
            logging.info("Skipping fix application - AI response indicates no issues found")
            return 0
        
        # Parser les corrections avec regex
        import re
        fix_pattern = r'=== FIX_FILE: (.+?) ===(.*?)=== END_FIX ==='
        fixes = re.findall(fix_pattern, ai_response, re.DOTALL)
        
        # SAFETY CHECK: Don't proceed if no proper fix patterns found
        if not fixes:
            if ("NO ISSUES" in ai_response.upper() or 
                "EVERYTHING IS GOOD" in ai_response.upper() or
                "ALL CODE VALIDATED" in ai_response.upper() or
                "NO FIXES NEEDED" in ai_response.upper()):
                logging.info("No fixes applied - AI response indicates no issues to fix")
                return 0
            else:
                logging.warning(f"No valid FIX_FILE patterns found in AI response: {ai_response[:200]}...")
                return 0
        
        for filename, file_content in fixes:
            filename = filename.strip()
            file_content = file_content.strip()
            
            try:                # Appliquer la correction
                file_path = target_path / filename
                file_path.parent.mkdir(parents=True, exist_ok=True)
                
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(file_content)
                
                # CRITIQUE: Nettoyer immédiatement les marqueurs markdown après correction
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    # Nettoyer les marqueurs markdown parasites
                    import re
                    original_content = content
                    content = re.sub(r'^```[a-zA-Z0-9_+-]*\n?', '', content, flags=re.MULTILINE)
                    content = re.sub(r'\n?```\s*$', '', content, flags=re.MULTILINE)
                    content = re.sub(r'^```[a-zA-Z0-9_+-]*$', '', content, flags=re.MULTILINE)
                    content = re.sub(r'^```$', '', content, flags=re.MULTILINE)
                    content = content.strip()
                    
                    # Réécrire si des marqueurs ont été supprimés
                    if content != original_content and content:
                        with open(file_path, 'w', encoding='utf-8') as f:
                            f.write(content)
                        logging.info(f"🧹 Auto-cleaned markdown artifacts from fixed file: {filename}")
                
                except Exception as cleanup_error:
                    logging.warning(f"Could not auto-clean markdown from {filename}: {cleanup_error}")
                
                fixes_applied += 1
                logging.info(f"Applied RepoMix fix to: {filename}")
                
            except Exception as e:
                logging.error(f"Error applying fix to {filename}: {e}")
                continue
        
        return fixes_applied
        
    except Exception as e:
        logging.error(f"Error applying fixes: {e}")
        return 0


def ensure_repomix_available():
    """
    S'assure que RepoMix est disponible, l'installe si nécessaire.
    
    Returns:
        bool: True si RepoMix est disponible
    """
    try:
        client = create_simple_codebase_client()
        return client.repomix_available
    except Exception as e:
        logging.error(f"Error checking RepoMix availability: {e}")
        return False


def clean_markdown_artifacts(target_directory):
    """
    Nettoie UNIVERSELLEMENT les marqueurs Markdown parasites dans TOUS les fichiers de code.
    Détecte automatiquement tous les langages et supprime ```language au début et ``` à la fin.
    
    Args:
        target_directory: Répertoire du projet
    
    Returns:
        int: Nombre de fichiers nettoyés
    """
    try:
        files_cleaned = 0
        target_path = Path(target_directory)
        
        # Extensions binaires à ignorer (performance + sécurité)
        binary_extensions = {
            '.exe', '.dll', '.so', '.dylib', '.bin', '.dat',
            '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.ico', '.svg',
            '.mp3', '.mp4', '.avi', '.mov', '.wav', '.pdf', '.zip',
            '.tar', '.gz', '.7z', '.rar', '.pyc', '.class', '.o'
        }
        
        # Parcourir TOUS les fichiers (approche universelle)
        for file_path in target_path.rglob('*'):
            if file_path.is_file():
                # Ignorer les fichiers binaires connus
                if file_path.suffix.lower() in binary_extensions:
                    continue
                
                # Ignorer les fichiers trop volumineux (probablement binaires)
                try:
                    if file_path.stat().st_size > 10 * 1024 * 1024:  # 10MB max
                        continue
                except:
                    continue                
                try:
                    # Tenter de lire le fichier comme du texte
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                    
                    # Ignorer les fichiers vides ou très courts
                    if len(content.strip()) < 10:
                        continue
                    
                    original_content = content
                      # NETTOYAGE UNIVERSEL - Détection automatique de patterns Markdown
                    import re
                    
                    # Supprimer les marqueurs de début ```[langage]
                    # Pattern ultra-robuste qui détecte TOUT langage possible
                    content = re.sub(r'^```[a-zA-Z0-9_+-]*\n?', '', content, flags=re.MULTILINE)
                    
                    # Supprimer les marqueurs de fin ``` (fin de fichier)
                    content = re.sub(r'\n?```\s*$', '', content, flags=re.MULTILINE)
                    
                    # Supprimer aussi les marqueurs en milieu de ligne (cas rares)
                    content = re.sub(r'^```[a-zA-Z0-9_+-]*$', '', content, flags=re.MULTILINE)
                    content = re.sub(r'^```$', '', content, flags=re.MULTILINE)
                    
                    # Supprimer les marqueurs RepoMix et autres artifacts spécifiques
                    content = re.sub(r'^---\s*END\s*OF\s*FILES?\s*---.*$', '', content, flags=re.MULTILINE | re.IGNORECASE)
                    content = re.sub(r'^--\s*END\s*FILE--.*$', '', content, flags=re.MULTILINE | re.IGNORECASE)
                    content = re.sub(r'^--\s*END--.*$', '', content, flags=re.MULTILINE)
                    content = re.sub(r'^###\s*END.*$', '', content, flags=re.MULTILINE)
                    content = re.sub(r'^\s*-{3,}\s*END\s*-{3,}.*$', '', content, flags=re.MULTILINE | re.IGNORECASE)
                    
                    # NEW: Remove AI-generated explanatory text and instructions
                    # Remove lines starting with **Note:** or **Setup Instructions:**
                    content = re.sub(r'^\*\*Note:\*\*.*$', '', content, flags=re.MULTILINE | re.IGNORECASE)
                    content = re.sub(r'^\*\*Setup Instructions.*$', '', content, flags=re.MULTILINE | re.IGNORECASE)
                    content = re.sub(r'^\*\*.*Instructions.*\*\*.*$', '', content, flags=re.MULTILINE | re.IGNORECASE)
                    content = re.sub(r'^\*\*End of.*\*\*.*$', '', content, flags=re.MULTILINE | re.IGNORECASE)
                    
                    # Remove markdown headers that shouldn't be in code files
                    content = re.sub(r'^#+\s+.*$', '', content, flags=re.MULTILINE)
                    
                    # Remove markdown bold text patterns that are explanations
                    content = re.sub(r'^\*\*.*\*\*\s*$', '', content, flags=re.MULTILINE)
                    
                    # Remove lines that look like documentation/instructions
                    content = re.sub(r'^-\s+.*download.*clone.*repository.*$', '', content, flags=re.MULTILINE | re.IGNORECASE)
                    content = re.sub(r'^-\s+.*browser.*chrome.*firefox.*$', '', content, flags=re.MULTILINE | re.IGNORECASE)
                    content = re.sub(r'^-\s+.*open.*index\.html.*$', '', content, flags=re.MULTILINE | re.IGNORECASE)
                    content = re.sub(r'^\d+\.\s+.*$', '', content, flags=re.MULTILINE)  # Numbered lists
                    
                    # Remove common instruction phrases
                    content = re.sub(r'^.*setup.*run.*instructions.*$', '', content, flags=re.MULTILINE | re.IGNORECASE)
                    content = re.sub(r'^.*features.*$', '', content, flags=re.MULTILINE | re.IGNORECASE)
                    content = re.sub(r'^.*usage.*$', '', content, flags=re.MULTILINE | re.IGNORECASE)
                    content = re.sub(r'^.*development.*$', '', content, flags=re.MULTILINE | re.IGNORECASE)
                    content = re.sub(r'^.*notes.*$', '', content, flags=re.MULTILINE | re.IGNORECASE)
                    
                    # Remove explanatory text blocks that start after code
                    content = re.sub(r'\n\n\*\*.*?\*\*.*$', '', content, flags=re.DOTALL)
                    content = re.sub(r'\n\n#.*$', '', content, flags=re.DOTALL)
                    
                    # NEW: Enhanced cleanup for AI-generated explanatory text at end of files
                    # Remove everything after "**Note:**" or similar explanatory markers
                    content = re.sub(r'\n\n\*\*Note:\*\*.*$', '', content, flags=re.DOTALL | re.IGNORECASE)
                    content = re.sub(r'\n\n\*\*Setup Instructions.*$', '', content, flags=re.DOTALL | re.IGNORECASE)
                    content = re.sub(r'\n\n\*\*End of code.*$', '', content, flags=re.DOTALL | re.IGNORECASE)
                    content = re.sub(r'\n\n## Features.*$', '', content, flags=re.DOTALL | re.IGNORECASE)
                    content = re.sub(r'\n\n## Setup and Run.*$', '', content, flags=re.DOTALL | re.IGNORECASE)
                    content = re.sub(r'\n\n## Usage.*$', '', content, flags=re.DOTALL | re.IGNORECASE)
                    content = re.sub(r'\n\n## Notes.*$', '', content, flags=re.DOTALL | re.IGNORECASE)
                    content = re.sub(r'\n\n## Development.*$', '', content, flags=re.DOTALL | re.IGNORECASE)
                    
                    # Remove specific instruction patterns that appear after code
                    content = re.sub(r'\n\n- The code is structured.*$', '', content, flags=re.DOTALL | re.IGNORECASE)
                    content = re.sub(r'\n\n- Download or clone.*$', '', content, flags=re.DOTALL | re.IGNORECASE)
                    content = re.sub(r'\n\n1\. Download.*$', '', content, flags=re.DOTALL | re.IGNORECASE)
                    content = re.sub(r'\n\n# To-Do List.*$', '', content, flags=re.DOTALL | re.IGNORECASE)
                    
                    # Clean up multiple empty lines
                    content = re.sub(r'\n{3,}', '\n\n', content)
                    
                    # Nettoyer les espaces excessifs en début/fin
                    content = content.strip()
                    
                    # Si le contenu a changé, réécrire le fichier
                    if content != original_content:
                        # Vérifier que le contenu nettoyé n'est pas vide
                        if content:
                            with open(file_path, 'w', encoding='utf-8') as f:
                                f.write(content)
                            
                            files_cleaned += 1
                            logging.info(f"🧹 Cleaned markdown artifacts from: {file_path.relative_to(target_path)}")
                        else:
                            logging.warning(f"⚠️ File became empty after cleaning: {file_path.relative_to(target_path)}")
                
                except UnicodeDecodeError:
                    # Fichier probablement binaire, ignorer
                    continue
                except Exception as e:
                    logging.warning(f"Could not clean file {file_path}: {e}")
                    continue
        
        return files_cleaned
        
    except Exception as e:
        logging.error(f"Error during markdown cleanup: {e}")
        return 0


# Test simple
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    if ensure_repomix_available():
        print("✅ Simplified RepoMix validation system ready")
    else:
        print("❌ RepoMix not available")