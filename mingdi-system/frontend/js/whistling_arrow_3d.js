const WHISTLING_ARROW_3D = (function () {
    let scene, camera, renderer, controls;
    let arrowGroup = null;
    let streamSurfaces = [];
    let soundFieldMesh = null;
    let animationId = null;
    let currentRotationSpeed = 100;
    let currentView = "3d";

    function initScene(canvasId) {
        const canvas = document.getElementById(canvasId);
        const container = canvas.parentElement;

        scene = new THREE.Scene();
        scene.background = new THREE.Color(0x050810);
        scene.fog = new THREE.Fog(0x050810, 20, 60);

        camera = new THREE.PerspectiveCamera(60, container.clientWidth / container.clientHeight, 0.1, 1000);
        camera.position.set(8, 4, 10);

        renderer = new THREE.WebGLRenderer({ canvas: canvas, antialias: true });
        renderer.setSize(container.clientWidth, container.clientHeight);
        renderer.setPixelRatio(window.devicePixelRatio);
        renderer.shadowMap.enabled = true;
        renderer.shadowMap.type = THREE.PCFSoftShadowMap;

        controls = new THREE.OrbitControls(camera, renderer.domElement);
        controls.enableDamping = true;
        controls.dampingFactor = 0.05;

        addLights();
        createGround();
        createArrow();
        createStreamSurfaces();
        createSoundField();

        window.addEventListener('resize', onWindowResize);
        animate();
    }

    function addLights() {
        const ambient = new THREE.AmbientLight(0x404060, 0.5);
        scene.add(ambient);

        const dirLight = new THREE.DirectionalLight(0xffffff, 1);
        dirLight.position.set(10, 20, 10);
        dirLight.castShadow = true;
        dirLight.shadow.mapSize.width = 2048;
        dirLight.shadow.mapSize.height = 2048;
        scene.add(dirLight);

        const fillLight = new THREE.DirectionalLight(0x6688ff, 0.3);
        fillLight.position.set(-10, 5, -10);
        scene.add(fillLight);
    }

    function createGround() {
        const groundGeo = new THREE.PlaneGeometry(50, 50, 50, 50);
        const groundMat = new THREE.MeshStandardMaterial({
            color: 0x1a2338,
            roughness: 0.8,
            metalness: 0.2
        });

        const positions = groundGeo.attributes.position;
        for (let i = 0; i < positions.count; i++) {
            const x = positions.getX(i);
            const z = positions.getZ(i);
            const y = Math.sin(x * 0.2) * 0.1 + Math.cos(z * 0.2) * 0.1;
            positions.setY(i, y);
        }
        groundGeo.computeVertexNormals();

        const ground = new THREE.Mesh(groundGeo, groundMat);
        ground.rotation.x = -Math.PI / 2;
        ground.position.y = -2;
        ground.receiveShadow = true;
        scene.add(ground);

        const gridHelper = new THREE.GridHelper(50, 50, 0x2a3a5c, 0x1a2338);
        gridHelper.position.y = -1.99;
        scene.add(gridHelper);
    }

    function createArrow() {
        arrowGroup = new THREE.Group();

        const arrowLength = 4;
        const shaftRadius = 0.06;
        const tipLength = 0.8;

        const shaftGeo = new THREE.CylinderGeometry(shaftRadius, shaftRadius, arrowLength - tipLength, 16);
        const shaftMat = new THREE.MeshStandardMaterial({ color: 0xd4a574, roughness: 0.6, metalness: 0.3 });
        const shaft = new THREE.Mesh(shaftGeo, shaftMat);
        shaft.position.y = (arrowLength - tipLength) / 2 - arrowLength / 2 + tipLength / 2;
        shaft.castShadow = true;
        shaft.receiveShadow = true;
        arrowGroup.add(shaft);

        const tipGeo = new THREE.ConeGeometry(shaftRadius * 1.5, tipLength, 16);
        const tipMat = new THREE.MeshStandardMaterial({ color: 0x8b7355, roughness: 0.4, metalness: 0.6 });
        const tip = new THREE.Mesh(tipGeo, tipMat);
        tip.position.y = (arrowLength - tipLength) / 2;
        tip.castShadow = true;
        arrowGroup.add(tip);

        const whistleGeo = new THREE.CylinderGeometry(0.12, 0.12, 0.3, 16);
        const whistleMat = new THREE.MeshStandardMaterial({
            color: 0xffd700, roughness: 0.3, metalness: 0.8,
            emissive: 0x332200, emissiveIntensity: 0.2
        });
        const whistle = new THREE.Mesh(whistleGeo, whistleMat);
        whistle.position.y = arrowLength / 2 - 0.8;
        whistle.castShadow = true;
        arrowGroup.add(whistle);

        for (let i = 0; i < 3; i++) {
            const holeAngle = (i / 3) * Math.PI * 2;
            const holeGeo = new THREE.CylinderGeometry(0.04, 0.04, 0.25, 8);
            const holeMat = new THREE.MeshStandardMaterial({ color: 0x1a1a1a, roughness: 0.9 });
            const hole = new THREE.Mesh(holeGeo, holeMat);
            hole.position.set(
                Math.cos(holeAngle) * 0.09,
                arrowLength / 2 - 0.8,
                Math.sin(holeAngle) * 0.09
            );
            hole.rotation.z = Math.PI / 2;
            hole.rotation.y = holeAngle;
            arrowGroup.add(hole);
        }

        const fletchCount = 3;
        const fletchLength = 0.6;
        const fletchHeight = 0.15;

        for (let i = 0; i < fletchCount; i++) {
            const angle = (i / fletchCount) * Math.PI * 2;
            const fletchShape = new THREE.Shape();
            fletchShape.moveTo(0, 0);
            fletchShape.quadraticCurveTo(fletchLength / 2, fletchHeight * 0.8, fletchLength, 0);
            fletchShape.lineTo(fletchLength * 0.7, -fletchHeight * 0.3);
            fletchShape.lineTo(0, 0);

            const fletchGeo = new THREE.ExtrudeGeometry(fletchShape, { depth: 0.01, bevelEnabled: false });
            const fletchMat = new THREE.MeshStandardMaterial({
                color: 0x2a3a5c, side: THREE.DoubleSide, roughness: 0.7
            });
            const fletch = new THREE.Mesh(fletchGeo, fletchMat);
            fletch.position.set(Math.cos(angle) * shaftRadius, -arrowLength / 2 + 0.4, Math.sin(angle) * shaftRadius);
            fletch.rotation.y = angle;
            fletch.rotation.x = -Math.PI / 2;
            fletch.castShadow = true;
            arrowGroup.add(fletch);
        }

        arrowGroup.rotation.z = Math.PI / 2;
        arrowGroup.rotation.y = -0.3;
        arrowGroup.position.x = 0;
        scene.add(arrowGroup);
    }

    function createStreamSurfaces() {
        const ribbonCount = 10;
        const pointsPerRibbon = 50;
        const ribbonWidth = 0.25;

        for (let r = 0; r < ribbonCount; r++) {
            const yStart = -3 + (6 * r / (ribbonCount - 1));
            let x = -8, y = yStart;
            const pathPoints = [];
            const speedFactors = [];

            for (let j = 0; j < pointsPerRibbon; j++) {
                const speedFactor = 1.0 - 0.4 * Math.exp(-(y * y / 4));
                pathPoints.push(new THREE.Vector3(x, y, 0));
                speedFactors.push(speedFactor);
                const vx = 1.0 * speedFactor;
                const vy = 0.05 * Math.sin(x * 0.3) + 0.02 * y;
                x += vx * 0.25;
                y += vy * 0.25;
                if (x > 8) break;
            }

            if (pathPoints.length < 3) continue;

            const { vertices, colors, indices } = buildRibbonBuffers(pathPoints, speedFactors, ribbonWidth);

            const geometry = new THREE.BufferGeometry();
            geometry.setAttribute('position', new THREE.Float32BufferAttribute(vertices, 3));
            geometry.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));
            geometry.setIndex(indices);
            geometry.computeVertexNormals();

            const material = new THREE.MeshBasicMaterial({
                vertexColors: true, transparent: true, opacity: 0.45,
                side: THREE.DoubleSide, depthWrite: false
            });

            const ribbon = new THREE.Mesh(geometry, material);
            ribbon.visible = false;
            streamSurfaces.push(ribbon);
            scene.add(ribbon);
        }
    }

    function buildRibbonBuffers(pathPoints, speedFactors, ribbonWidth) {
        const vertices = [];
        const colors = [];
        const indices = [];

        for (let i = 0; i < pathPoints.length; i++) {
            const p = pathPoints[i];
            const sf = speedFactors[i];

            let tangent;
            if (i === 0) {
                tangent = new THREE.Vector3().subVectors(pathPoints[1], pathPoints[0]).normalize();
            } else if (i === pathPoints.length - 1) {
                tangent = new THREE.Vector3().subVectors(pathPoints[i], pathPoints[i - 1]).normalize();
            } else {
                tangent = new THREE.Vector3().subVectors(pathPoints[i + 1], pathPoints[i - 1]).normalize();
            }

            const normal = new THREE.Vector3(-tangent.y, tangent.x, 0).normalize();
            const halfWidth = ribbonWidth * 0.5 * (0.4 + 0.6 * sf);

            const p1 = new THREE.Vector3().copy(p).addScaledVector(normal, halfWidth);
            const p2 = new THREE.Vector3().copy(p).addScaledVector(normal, -halfWidth);

            vertices.push(p1.x, p1.y, p1.z);
            vertices.push(p2.x, p2.y, p2.z);

            const t = sf;
            const r = 0.2 + t * 0.3, g = 0.5 + t * 0.2, b = 0.9 - t * 0.1;
            colors.push(r, g, b);
            colors.push(r, g, b);

            if (i < pathPoints.length - 1) {
                const base = i * 2;
                indices.push(base, base + 1, base + 2);
                indices.push(base + 1, base + 3, base + 2);
            }
        }
        return { vertices, colors, indices };
    }

    function createSoundField() {
        const size = 10;
        const segments = 50;
        const geometry = new THREE.PlaneGeometry(size, size, segments, segments);
        const material = new THREE.MeshBasicMaterial({
            vertexColors: true, transparent: true, opacity: 0.3, side: THREE.DoubleSide
        });

        soundFieldMesh = new THREE.Mesh(geometry, material);
        soundFieldMesh.rotation.x = -Math.PI / 2;
        soundFieldMesh.position.y = -1.9;
        soundFieldMesh.visible = false;
        scene.add(soundFieldMesh);
        updateSoundField(85);
    }

    function updateSoundField(spl) {
        if (!soundFieldMesh) return;
        const geometry = soundFieldMesh.geometry;
        const positions = geometry.attributes.position;
        const colors = [];
        const maxDist = 5;

        for (let i = 0; i < positions.count; i++) {
            const x = positions.getX(i);
            const z = positions.getZ(i);
            const dist = Math.sqrt(x * x + z * z);
            const localSpl = spl - 20 * Math.log10(Math.max(dist, 0.1)) + Math.random() * 2;
            const t = Math.max(0, Math.min(1, (localSpl - 40) / 60));
            const color = splColor(t);
            colors.push(color.r, color.g, color.b);
        }

        geometry.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));
        geometry.attributes.color.needsUpdate = true;
    }

    function splColor(t) {
        const c = new THREE.Color();
        if (t < 0.25) {
            c.setRGB(0, 0.1, 0.3 + t);
        } else if (t < 0.5) {
            const tt = (t - 0.25) / 0.25;
            c.setRGB(0, 0.2 + tt * 0.6, 0.6 - tt * 0.3);
        } else if (t < 0.75) {
            const tt = (t - 0.5) / 0.25;
            c.setRGB(tt, 0.8 - tt * 0.3, 0.3 - tt * 0.2);
        } else {
            const tt = (t - 0.75) / 0.25;
            c.setRGB(1, 0.5 - tt * 0.4, 0.1 - tt * 0.1);
        }
        return c;
    }

    function updateStreamSurfaces(velocity) {
        const ribbonCount = streamSurfaces.length;
        const ribbonWidth = 0.25;
        const factor = velocity / 65;

        streamSurfaces.forEach((ribbon, r) => {
            const yStart = -3 + (6 * r / (ribbonCount - 1));
            let x = -8, y = yStart;
            const pathPoints = [];
            const speedFactors = [];

            for (let j = 0; j < 50; j++) {
                const speedFactor = 1.0 - 0.4 * Math.exp(-(y * y / 4));
                pathPoints.push(new THREE.Vector3(x, y, 0));
                speedFactors.push(speedFactor);
                const vx = factor * speedFactor;
                const vy = 0.05 * Math.sin(x * 0.3) + 0.02 * y;
                x += vx * 0.25;
                y += vy * 0.25;
                if (x > 8) break;
            }

            if (pathPoints.length < 3) return;

            const { vertices, colors, indices } = buildRibbonBuffers(pathPoints, speedFactors, ribbonWidth);

            const posAttr = ribbon.geometry.attributes.position;
            if (posAttr && posAttr.count === vertices.length / 3) {
                posAttr.array.set(new THREE.Float32BufferAttribute(vertices, 3).array);
                posAttr.needsUpdate = true;
                ribbon.geometry.attributes.color.array.set(new THREE.Float32BufferAttribute(colors, 3).array);
                ribbon.geometry.attributes.color.needsUpdate = true;
                ribbon.geometry.computeVertexNormals();
            } else {
                ribbon.geometry.dispose();
                const newGeo = new THREE.BufferGeometry();
                newGeo.setAttribute('position', new THREE.Float32BufferAttribute(vertices, 3));
                newGeo.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));
                newGeo.setIndex(indices);
                newGeo.computeVertexNormals();
                ribbon.geometry = newGeo;
            }
        });
    }

    function setView(view) {
        currentView = view;
        streamSurfaces.forEach(ribbon => {
            ribbon.visible = (view === 'flow' || view === '3d');
        });
        if (soundFieldMesh) {
            soundFieldMesh.visible = (view === 'acoustic' || view === '3d');
            soundFieldMesh.material.opacity = view === 'acoustic' ? 0.6 : 0.2;
        }
        if (arrowGroup) {
            arrowGroup.visible = (view === '3d' || view === 'flow' || view === 'acoustic');
        }
    }

    function setRotationSpeed(rs) {
        currentRotationSpeed = rs;
    }

    function animate() {
        animationId = requestAnimationFrame(animate);
        if (arrowGroup) {
            arrowGroup.rotation.x += currentRotationSpeed * 0.001;
            arrowGroup.position.y = Math.sin(Date.now() * 0.001) * 0.2;
        }
        controls.update();
        renderer.render(scene, camera);
    }

    function onWindowResize() {
        const container = document.getElementById('three-canvas').parentElement;
        camera.aspect = container.clientWidth / container.clientHeight;
        camera.updateProjectionMatrix();
        renderer.setSize(container.clientWidth, container.clientHeight);
    }

    return {
        init: initScene,
        updateStreamSurfaces,
        updateSoundField,
        setView,
        setRotationSpeed
    };
})();
