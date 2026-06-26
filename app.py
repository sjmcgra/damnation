# DAMnation -- Self-hosted Digital Asset Management
# Copyright (C) 2026 Sean McGrath (github.com/sjmcgra)
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# See LICENSE for the full license text, or visit:
# https://www.gnu.org/licenses/gpl-3.0.html
#
# Built with DAMnation -- powering Hokai (hokaiprime.com)

from flask import Flask, render_template, request, send_file, jsonify
import sqlite3
from pathlib import Path
import json
import subprocess
import os
import git
from datetime import datetime

from config import DB_PATH, THUMBNAIL_DIR, PROJECTS_ROOT, get_repo_url, GIT_SSH_COMMAND, FLASK_ENV, GIT_BRANCH

app = Flask(__name__, template_folder='templates', static_folder='static')
app.config['ENV'] = FLASK_ENV
app.config['DEBUG'] = FLASK_ENV == 'development'

# Create directories if they don't exist
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
THUMBNAIL_DIR.mkdir(parents=True, exist_ok=True)

def get_db():
    """Get database connection"""
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        return conn
    except Exception as e:
        print(f"Database connection error: {e}")
        raise

def format_size(size_bytes):
    """Format bytes to human readable format"""
    if size_bytes is None:
        return "0 B"
    size_bytes = int(size_bytes)
    if size_bytes == 0:
        return "0 B"
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"

def format_file_type(file_type):
    """Format file type for display"""
    if not file_type:
        return "Unknown"
    # Map specific types to user-friendly names
    type_map = {
        'application/x-motion': 'Motion',
        'application/x-garageband': 'GarageBand',
        'image/png': 'Image',
        'image/jpeg': 'Image',
        'image/webp': 'Image',
        'video/mp4': 'Video',
        'video/quicktime': 'Video',
        'video/x-msvideo': 'Video',
        'audio/wav': 'Audio',
        'audio/mpeg': 'Audio',
        'model/blender': '3D Model',
        'model/gltf-binary': '3D Model',
        'model/fbx': '3D Model',
        'model/obj': '3D Model',
    }
    # Check exact match first
    if file_type in type_map:
        return type_map[file_type]
    # Otherwise return first part (e.g., 'image' from 'image/jpeg')
    return file_type.split('/')[0].upper()

@app.route('/')
def index():
    """Home page with search"""
    query = request.args.get('q', '')
    project = request.args.get('project', '')
    file_type = request.args.get('type', '')
    show_all = request.args.get('all', '').lower() == 'true'
    page = request.args.get('page', default=1, type=int)
    page = max(1, page)  # Ensure page is at least 1
    per_page = 20
    
    db = get_db()
    
    # Build base query
    sql = "SELECT * FROM assets WHERE 1=1"
    params = []
    
    if query:
        sql += " AND (tags LIKE ? OR filename LIKE ?)"
        params.extend([f"%{query}%", f"%{query}%"])
    
    if project:
        sql += " AND project = ?"
        params.append(project)
    
    if file_type:
        if file_type == 'motion':
            # Special case for Motion files (.motn)
            sql += " AND file_type = ?"
            params.append('application/x-motion')
        elif file_type == 'garageband':
            # Special case for GarageBand files (.band)
            sql += " AND file_type = ?"
            params.append('application/x-garageband')
        else:
            sql += " AND file_type LIKE ?"
            params.append(f"{file_type}%")
    
    sql += " ORDER BY indexed_date DESC"
    
    # Get total count for pagination (unique by filepath)
    count_sql = f"SELECT COUNT(DISTINCT filepath) as count FROM ({sql})"
    count_result = db.execute(count_sql, params).fetchone()
    total_count = count_result['count']
    
    # Remove duplicates by grouping - get latest entry for each filepath
    # Use a subquery to get the latest entry for each filepath
    group_sql = f"""
        SELECT DISTINCT 
            MIN(id) as id,
            project,
            filepath,
            filename,
            file_type,
            file_size,
            width,
            height,
            dvc_hash,
            thumbnail_path,
            tags,
            created_date,
            indexed_date,
            git_commit,
            is_bundle,
            bundle_path,
            bundle_files,
            archived,
            archive_source
        FROM (
            {sql}
        )
        GROUP BY project, filepath
        ORDER BY indexed_date DESC
    """
    
    # Add pagination if not showing all
    if not show_all:
        offset = (page - 1) * per_page
        group_sql += f" LIMIT ? OFFSET ?"
        params.extend([per_page, offset])
    
    results = db.execute(group_sql, params).fetchall()
    
    # Fetch git version history for each result
    results_with_versions = []
    for asset in results:
        versions = []
        try:
            repo_path = PROJECTS_ROOT / asset['project']
            if repo_path.exists():
                repo = git.Repo(repo_path)
                # Git path needs to be relative to repo root (include 'assets/' prefix)
                git_filepath = f"assets/{asset['filepath']}"
                commits = list(repo.iter_commits(paths=git_filepath))
                
                # Only show commits for files with actual git history
                # (Skip DVC-tracked files which show up in assets.dvc commits instead)
                for commit in commits:
                    versions.append({
                        'hexsha': commit.hexsha[:8],
                        'author': commit.author.name,
                        'date': datetime.fromtimestamp(commit.committed_date).isoformat(),
                        'message': commit.message.strip()
                    })
        except Exception as e:
            print(f"Error getting versions for {asset['filepath']}: {e}")
        
        # Convert sqlite Row to dict and add versions
        asset_dict = dict(asset)
        asset_dict['versions'] = versions
        asset_dict['version_count'] = len(versions)
        results_with_versions.append(asset_dict)
    
    # Calculate pagination info
    total_pages = (total_count + per_page - 1) // per_page if not show_all else 1
    has_next = page < total_pages if not show_all else False
    has_prev = page > 1
    
    # Get list of projects for filter
    projects = db.execute("SELECT DISTINCT project FROM assets ORDER BY project").fetchall()
    
    db.close()
    
    return render_template('index.html', 
                         results=results_with_versions, 
                         projects=projects,
                         query=query,
                         selected_project=project,
                         selected_type=file_type,
                         format_file_type=format_file_type,
                         page=page,
                         total_pages=total_pages,
                         total_count=total_count,
                         has_next=has_next,
                         has_prev=has_prev,
                         show_all=show_all,
                         per_page=per_page)

@app.route('/thumbnail/<path:thumb_path>')
def thumbnail(thumb_path):
    """Serve thumbnail image"""
    full_path = THUMBNAIL_DIR.parent / thumb_path
    if full_path.exists():
        return send_file(full_path, mimetype='image/jpeg')
    return "Thumbnail not found", 404

@app.route('/download/<project>/<path:filepath>')
def download(project, filepath):
    """Download file from local filesystem or S3 via DVC"""
    try:
        # Try local filesystem first (faster for production assets)
        file_path = PROJECTS_ROOT / project / "assets" / filepath
        
        if file_path.exists():
            filename = Path(filepath).name
            return send_file(str(file_path), 
                           as_attachment=True, 
                           download_name=filename)
        
        # Fallback: retrieve from DVC/S3 for archived assets
        try:
            import tempfile
            import shutil
            
            # Create temporary file for DVC output
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                tmp_path = tmp.name
            
            # Use dvc get to retrieve from remote (S3)
            repo_url = get_repo_url(project)
            env = os.environ.copy()
            env["GIT_SSH_COMMAND"] = GIT_SSH_COMMAND
            result = subprocess.run([
                'dvc', 'get', '-o', tmp_path,
                repo_url,
                filepath
            ], capture_output=True, text=True, env=env)
            
            if result.returncode == 0 and Path(tmp_path).exists():
                filename = Path(filepath).name
                return send_file(tmp_path, 
                               as_attachment=True, 
                               download_name=filename)
            else:
                return f"File not found in S3: {result.stderr}", 404
                
        except Exception as dvc_err:
            return f"File not found locally or in S3: {str(dvc_err)}", 404
            
    except Exception as e:
        return f"Error: {str(e)}", 500

@app.route('/view/<project>/<path:filepath>')
def view_file(project, filepath):
    """View file in browser (stream for images, videos, audio)"""
    try:
        import mimetypes
        import tempfile
        
        # Try to get from local projects first
        file_path = PROJECTS_ROOT / project / "assets" / filepath
        
        if file_path.exists():
            # Get MIME type
            mime_type, _ = mimetypes.guess_type(str(file_path))
            if mime_type is None:
                mime_type = 'application/octet-stream'
            
            # Determine if it's viewable in browser
            viewable_types = ['image/', 'video/', 'audio/']
            is_viewable = any(mime_type.startswith(vt) for vt in viewable_types)
            
            if is_viewable:
                return send_file(str(file_path), mimetype=mime_type)
            else:
                return f"File type not viewable in browser: {mime_type}", 400
        
        # Fallback: retrieve from DVC/S3 for archived assets
        try:
            # Get MIME type
            mime_type, _ = mimetypes.guess_type(filepath)
            if mime_type is None:
                mime_type = 'application/octet-stream'
            
            # Determine if it's viewable
            viewable_types = ['image/', 'video/', 'audio/']
            is_viewable = any(mime_type.startswith(vt) for vt in viewable_types)
            
            if not is_viewable:
                return f"File type not viewable in browser: {mime_type}", 400
            
            # Create temporary file for DVC output
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                tmp_path = tmp.name
            
            # Use dvc get to retrieve from remote (S3)
            repo_url = get_repo_url(project)
            env = os.environ.copy()
            env["GIT_SSH_COMMAND"] = GIT_SSH_COMMAND
            result = subprocess.run([
                'dvc', 'get', '-o', tmp_path,
                repo_url,
                filepath
            ], capture_output=True, text=True, env=env)
            
            if result.returncode == 0 and Path(tmp_path).exists():
                return send_file(tmp_path, mimetype=mime_type)
            else:
                return f"File not found in S3: {result.stderr}", 404
                
        except Exception as dvc_err:
            return f"File not found locally or in S3: {str(dvc_err)}", 404
            
    except Exception as e:
        return f"Error: {str(e)}", 500

@app.route('/asset/<int:asset_id>')
def asset_detail(asset_id):
    """Show asset detail page with versions and download options"""
    db = get_db()
    asset = db.execute("SELECT * FROM assets WHERE id = ?", (asset_id,)).fetchone()
    
    if not asset:
        db.close()
        return "Asset not found", 404
    
    # Get version history from git
    versions = []
    try:
        repo_path = PROJECTS_ROOT / asset['project']
        if repo_path.exists():
            repo = git.Repo(repo_path)
            # Get commits that modified this file (include assets/ prefix for git)
            git_filepath = f"assets/{asset['filepath']}"
            commits = list(repo.iter_commits(paths=git_filepath))
            # Only show if file has actual git history (not DVC-tracked)
            for commit in commits:
                versions.append({
                    'hexsha': commit.hexsha[:8],
                    'author': commit.author.name,
                    'date': datetime.fromtimestamp(commit.committed_date).isoformat(),
                    'message': commit.message.strip()
                })
    except Exception as e:
        print(f"Error getting versions: {e}")
    
    db.close()
    
    return render_template('asset_detail.html', 
                         asset=asset, 
                         versions=versions,
                         format_size=format_size,
                         format_file_type=format_file_type)

@app.route('/api/assets/<int:asset_id>/versions')
def api_asset_versions(asset_id):
    """API endpoint to get asset version history"""
    db = get_db()
    asset = db.execute("SELECT * FROM assets WHERE id = ?", (asset_id,)).fetchone()
    
    if not asset:
        db.close()
        return jsonify({'error': 'Asset not found'}), 404
    
    versions = []
    try:
        repo_path = PROJECTS_ROOT / asset['project']
        if repo_path.exists():
            repo = git.Repo(repo_path)
            # Git path needs to be relative to repo root (include 'assets/' prefix)
            git_filepath = f"assets/{asset['filepath']}"
            commits = list(repo.iter_commits(paths=git_filepath))
            # Only show if file has actual git history (not DVC-tracked)
            for commit in commits:
                versions.append({
                    'hexsha': commit.hexsha,
                    'short_sha': commit.hexsha[:8],
                    'author': commit.author.name,
                    'date': datetime.fromtimestamp(commit.committed_date).isoformat(),
                    'message': commit.message.strip()
                })
    except Exception as e:
        print(f"Error getting versions: {e}")

    
    db.close()
    return jsonify(versions)

@app.route('/download/<project>/version/<version>/<path:filepath>')
def download_version(project, version, filepath):
    """Download specific version of file from DVC"""
    try:
        repo_path = PROJECTS_ROOT / project
        
        # Checkout specific version
        result = subprocess.run([
            'git', 'checkout', version, '--', filepath
        ], cwd=repo_path, capture_output=True, text=True)
        
        if result.returncode != 0:
            return f"Git checkout failed: {result.stderr}", 500
        
        # Pull from DVC for that version
        result = subprocess.run([
            'dvc', 'checkout', filepath
        ], cwd=repo_path, capture_output=True, text=True)
        
        if result.returncode != 0:
            return f"DVC checkout failed: {result.stderr}", 500
        
        # Copy to temp location
        file_path = repo_path / filepath
        temp_path = Path(f'/tmp/download_{version[:8]}')
        
        import shutil
        shutil.copy(file_path, temp_path)
        
        # Return to configured branch
        subprocess.run(['git', 'checkout', GIT_BRANCH], cwd=repo_path)
        subprocess.run(['dvc', 'checkout'], cwd=repo_path)
        
        filename = Path(filepath).name
        return send_file(str(temp_path), 
                       as_attachment=True, 
                       download_name=f"{Path(filepath).stem}_v{version[:8]}{Path(filepath).suffix}")
            
    except Exception as e:
        return f"Error: {str(e)}", 500

@app.route('/api/archive/<int:asset_id>', methods=['POST'])
def archive_asset(asset_id):
    """Mark an asset as archived and optionally set archive source"""
    try:
        archive_source = request.json.get('archive_source', '') if request.is_json else ''
        
        db = get_db()
        db.execute('UPDATE assets SET archived=1, archive_source=? WHERE id=?', 
                   (archive_source, asset_id))
        db.commit()
        db.close()
        
        return jsonify({'success': True, 'message': f'Asset {asset_id} marked as archived'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/unarchive/<int:asset_id>', methods=['POST'])
def unarchive_asset(asset_id):
    """Mark an asset as active again"""
    try:
        db = get_db()
        db.execute('UPDATE assets SET archived=0, archive_source=NULL WHERE id=?', 
                   (asset_id,))
        db.commit()
        db.close()
        
        return jsonify({'success': True, 'message': f'Asset {asset_id} marked as active'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/stats')
def stats():
    """Show statistics"""
    db = get_db()
    
    stats_data = {
        'total_assets': db.execute("SELECT COUNT(*) as count FROM assets").fetchone()['count'],
        'by_project': [],
        'by_type': [],
        'total_size': db.execute("SELECT SUM(file_size) as size FROM assets").fetchone()['size'] or 0
    }
    
    # Convert dicts to lists for template
    projects = db.execute("SELECT project, COUNT(*) as count FROM assets GROUP BY project ORDER BY count DESC").fetchall()
    types = db.execute("SELECT file_type, COUNT(*) as count FROM assets GROUP BY file_type ORDER BY count DESC").fetchall()
    
    stats_data['by_project'] = [{'name': p['project'], 'count': p['count']} for p in projects]
    stats_data['by_type'] = [{'name': format_file_type(t['file_type']), 'count': t['count']} for t in types]
    
    db.close()
    
    return render_template('stats.html', 
                         stats=stats_data, 
                         format_size=format_size,
                         format_file_type=format_file_type,
                         now=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

@app.route('/download-bundle/<project>/<path:bundle_path>')
def download_bundle(project, bundle_path):
    """Download entire Motion project bundle as zip"""
    import zipfile
    import tempfile
    
    try:
        # Full path to the bundle directory
        full_bundle_path = PROJECTS_ROOT / project / "assets" / bundle_path
        
        if not full_bundle_path.exists():
            return f"Bundle not found: {bundle_path}", 404
        
        # Create temporary zip file
        temp_zip = tempfile.NamedTemporaryFile(delete=False, suffix='.zip')
        
        with zipfile.ZipFile(temp_zip.name, 'w', zipfile.ZIP_DEFLATED) as zipf:
            # Add all files in the bundle directory
            for file_path in full_bundle_path.rglob('*'):
                if file_path.is_file():
                    arcname = file_path.relative_to(full_bundle_path.parent)
                    zipf.write(file_path, arcname)
        
        bundle_name = Path(bundle_path).name
        return send_file(temp_zip.name,
                        as_attachment=True,
                        download_name=f"{bundle_name}.zip")
        
    except Exception as e:
        return f"Error: {str(e)}", 500

# Error handlers
@app.errorhandler(404)
def not_found(error):
    """Handle 404 errors"""
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    """Handle 500 errors"""
    return render_template('500.html'), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5500, debug=True)